# Phase 5 — Thiết kế chi tiết (đủ 4 loại yêu cầu: T22a luật, T20 phân loại + tách ý, T23 B2, T24 executor + hoàn tác)

*Thuộc bộ `build/`. Phiên bản **0.14 — 18/10/2026** (0.14: mục 7.14 khớp đặc tả v0.6 — Tuấn Anh chốt 4 điểm lúc 03:25: bộ đếm tin nhắn gồm `/confirm`, đếm bằng bảng `rate_hits` trong `0010`; 3 luật đo ghi trước vào D-52; tối đa 3 phiên coding agent 18–21/10; Claude chép tài liệu vào `docs/spec`. 0.13: mục 7.14 khớp đặc tả v0.5 sau lượt soát 3 người độc lập — gói 1 chia 2 DỪNG, việc trước khi mở phiên, luật dùng stack, thứ tự tối 20/10, 7 điểm chờ duyệt; mục 8 dòng 18–21. 0.12: **mục 7.14 — sau cổng 5: bật 2 model phân loại (B2 `review`, B3 ghi điểm), chống dò và spam, B3-VA** (D-52…D-55, lịch 18–21/10 trên 2 worktree); bảng kế hoạch tóm tắt dòng 6–10; mục 8 thêm 18–21/10. 0.11: 7.12 dòng 3 — LLM-G DỪNG 3 `3cf0d18` (3 prompt, vpn-smoke 53/0, D-51) + việc treo tải song song; **7.13 — cổng 5 thủ công ĐẠT 18/10**. 0.10: mục 1.3 cổng 5 thủ công 45 câu, 5 lớp; 7.11 bảng S4 "mở rộng 1 → 4 loại tốn gì"; 7.12 LLM-G; **7.13 phần thủ công cổng 5 còn nợ**. 0.9: mục 7.12 — V16 dấu vết 401 + bước CI verify; V17 mô tả R17–R19. 0.8: **cổng 5 ĐẠT 15/10** — lịch mục 8; gate2 bỏ phụ thuộc FAKE_* trong `.env` ở `24c5012`. 0.7: mục 7.11 chốt khi hiện thực T24 (viết bù; nợ compose `ENABLED_INTENTS`). 0.6: **T20b đóng** `14316ad` + `5df24c7` + `8a7c697` (verify G=2345 lần 3 gate2/3/4 xanh + G=5 gate5 227/0) — mục 5.2.13 chốt khi hiện thực (Q-T20b-1…13); lịch mục 8 (6C DỪNG 15/16, cổng 5 ~17/10). 0.5: **T24 đóng** `457239d` (CI xanh, PR #39 → main `e000d03`); **T20b viết đủ** (mục 5.2, soát code tại `90ee85d`; Q5 = con vào B6, ý lẫn = tách — Tuấn Anh chốt 13/10). 0.4: **T20a đóng** `03b4450` — mục 5.1.11 chốt khi hiện thực (16 mục); **T24 viết đủ** (mục 7, soát code tại `03b4450`). 0.3: **T23a đóng** `a463150`; **T20a viết đủ** (mục 5.1, soát code tại `6cf1091` — K2 PR #29 đã gộp + ingest); áp 17 mục "Spec cần sửa (T22a)" (mục 4.14 + sửa tại chỗ 4.1 P7/P9, 4.2, 4.5, 4.7, 4.8, 4.10) và 11 mục "Spec cần sửa (T23a)" (mục 6.5); lịch mục 8. Bản 0.2 — 10/10: T22a đóng `2ffb005`, T20 tách T20a/T20b, bật intent dời sang T24, D-44…D-46. Bản 0.1f — 09/10: `procedure_doc` theo K2, luật git 4.0. Nguồn: `huong-dan-xay-dung-he-thong-2.md` §5 Phase 5, §7.1; `NGU-CANH-DAY-DU.md` Phần I §6.3 (bảng luật); `build/decisions.md` §1.1 (R01–R20), D-34, D-41, D-44…D-47; `B12-B14` v1.2 (DSL §4.2); `B11` v1.5 (slot, `Action`); `P8` §4; `claude/phase5-6-phan-tich-va-chia-chang.md` (G5-x, lịch). Mốc code: T22a dựng trên `3ff63e1`; T23a trên `d42d5c4`; T20a trên `6cf1091`.*

*Nhãn: **[Chốt]** spec gốc đã chốt · **[Chốt 01/10]**, **[Chốt 09/10]** Tuấn Anh chốt ngày đó · **[Đề xuất]** Claude chat đề xuất, Tuấn Anh soát khi duyệt PLAN · **[Suy luận]** agent phải kiểm lại trên code.*

**Kế hoạch tóm tắt (đọc trước):**

| Thứ tự | Chặng | Nội dung | Tầng | DỪNG | Model | Mở khi |
|---|---|---|---|---|---|---|
| 1 | **T22a** | 15 luật R01–R15 + fact mới + nguồn `action.params` + `build_ctx` theo đích + khai báo 3 intent (không bật) + seed 3 trường + `rule_coverage.py` (mục 4) | **A** | 2 | **Opus** | Cây chính sạch + bảng 4.2 chốt + đã pull `3ff63e1` — **đạt 09/10** (làm sớm — "chưa tính qua cổng 5") |
| 2 | **T23a** | B2 lớp 3 `shadow` — đóng `ml-gan` (mục 6) — **ĐÓNG** `a463150` | **A** | 1 | **Opus** | 6B gộp — đạt 10/10 |
| 3 | **T20a** | B6/B11 + `Action` đơn ý cho account/software/access, fact `existing_permission_level` + R10, roster, tin từ chối theo đích (mục 5.1) — **ĐÓNG** `03b4450` | **A** + B | 2 | **Opus** | đạt 12/10 |
| 4 | **T24** | `PLAN` + hoàn tác 6 hành động mới + B18 + **bật 4 intent** + `make gate5` (mục 7) — **ĐÓNG** `457239d` | **A** | 2 | **Opus** | đạt 13/10 |
| 5 | **T20b** | Nhiều ý: B5 tách ticket con (con vào B6), vòng cha một tin mỗi lượt (D-31), `POST /reply`, gate5 nhiều ý (mục 5.2) — **ĐÓNG** `8a7c697` | **A** | 2 | **Opus** | đạt 13/10 |
| 6 | **Gói 1** | B2 `review` + E1 `injection_suspected` + nợ bảo mật §6.5 + hàng chờ classify riêng + script đo (mục 7.14, D-52) | **A** | theo lời mở | **Opus** | 18/10, sau khi DỪNG 3 push |
| 7 | **Gói 2** | B3 ghi điểm — bộ nạp intent vào ml-service (mục 7.14, D-53) | **A** | theo lời mở | **Opus** | 19/10, sau gói 1 |
| 8 | **B3-VA** | Câu nhiều ý có ý không chắc: bước "dính nhau" (mục 7.14, D-55; prompt `claude/prompt-b3-va.md`) | **A** | MẪU A, B1, B2 | **Opus** | 19/10, sau gói 2 (cùng `b03_classify.py`) |
| 9 | **Gói 2b** | Chống spam 429, luật M9 `requester_probe`, trang Cảnh báo cho L2, dòng lịch sử người gửi cho L2 (mục 7.14, D-54) | **A** | theo phần | **Opus** | 18/10, worktree riêng |
| 10 | **Gói 3** | Vai trò `judge` cho LLM chấm — chỉ khi Gemini/Qwen qua phép thử (mục 7.14) | **A** | theo lời mở | **Opus** | 20/10 chiều |

Mỗi chặng = **một phiên agent mới**. Tối đa 2 phiên coding agent cùng lúc trên cả dự án (lịch: `claude/phase5-6-phan-tich-va-chia-chang.md` mục 5). Ngoại lệ 18–21/10: tối đa 3 (mục 7.14, Tuấn Anh chốt 18/10).

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
- **Song song Phase 6 (`claude/giao-thuc-phase5-6.md`, Phase 6 giữ bút):** tối đa 2 agent cùng lúc trên cả dự án (18–21/10: 3 — mục 7.14); không hai DỪNG tầng A cùng ngày; T22a ↔ 6A chỉ chung `PROGRESS.md` (bên gộp sau: phiên git giữ cả hai mục, agent không tự giải); không thêm module/import `app.eval` vào `backend/app/risk/` (test AST của 6A quét cả thư mục); 6B mở sau khi T22a đẩy; T20 mở sau khi 6B gộp; 6C mở sau khi T24 đẩy. Tin chéo phase qua `claude/tin-p5-sang-p6.md` / `claude/tin-p6-sang-p5.md`.
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

**Thủ công (dồn mốc G):** intent macro-F1 ≥ 0,85 / 45 câu (10/loại × 4 + 5 ngoài phạm vi, macro-F1 5 lớp; bộ câu chỉ để đo — chốt 15/10); chặn ≥ 13/15 tấn công, chặn nhầm ≤ 1/30; Recall@5 ≥ 0,8 / 30 câu; ghi chú bàn giao E7 đủ 4 phần.

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
| **P7** | **Seed mock (G5-3)** `mock_services/seed.json` + model đầu ra tool `backend/app/tools/models.py` + model mock tương ứng: user thêm `is_service_account: bool` (`svc_backup` = `true`, còn lại `false`), `disable_reason: "security" \| "other" \| null` (chỉ có giá trị khi `employment_status == "disabled"`; `nv004` = `"security"`); catalog thêm `requires_local_admin: bool` (`autocad` = `true`, còn lại `false`). Test mock + test tool-vs-mock sửa kỳ vọng có lý do. Endpoint quản trị đổi trạng thái (`mock_services/app/admin_calls.py` `POST /_admin/users/{id}/status`): chuyển khỏi `disabled` → đặt `disable_reason = null`; chuyển sang `disabled` không kèm lý do → `null` (hợp lệ: thiếu lý do ⇒ R12 không khớp, R10 cũng không — ca e12b). **[Chốt khi hiện thực T22a]** seed model mock cũng **không** mặc định 3 trường (khoá bắt buộc; `seed.json` ghi tường minh cho 17 người + 7 mục catalog); endpoint quản trị nhận `disable_reason` tuỳ chọn ∈ {security, other}, trạng thái đích ≠ `disabled` → luôn `null`. Không thêm người/máy mới ở T22a (cần thì T20 thêm). Hình dạng model tool: xem cuối mục 4.7b |
| **P8** | **`policy.json`**: thêm R01–R15 theo **bảng 4.4 nguyên văn** (thứ tự R01…R20 tăng dần trong file); `description` là câu tiếng Việt ngắn đọc được bởi Trưởng BP (bảng 4.4 cột "Mô tả"). Không đổi `constants`, `business_hours`, R16–R20 |
| **P9** | **`scripts/rule_coverage.py`** (Q-5-5, mục 4.6) — chỉ đọc, không gọi mạng, không cần stack; dùng `app.domain`, `app.risk.policy_engine.evaluate_rules` và loader **theo đường dẫn** (`load_policy`, `load_action_metadata`, `intents_of_actions`) — **không** `get_settings()` (đọc `.env`); tự chèn `backend/` vào `sys.path`; `main(argv) -> int`; không import `app.eval` [Chốt khi hiện thực T22a] |
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
- `value_rules` (slots.yaml): `account_type` pattern `^(ad|email|erp)$`; `target_user` `^[a-z0-9_]{3,64}$`; `software_name` `^[A-Za-z0-9][A-Za-z0-9 .+#-]{0,63}$`; `resource_path` `^[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+){0,4}$` (nhận chữ hoa: tên hiển thị "Zoom Workplace", "AutoCAD", thư mục `finance/Q3`; mock tự chuẩn hoá tên phần mềm nên slot nhận tên người dùng gõ); `permission_level` `^(read|write|full)$`; `duration` `^\d{1,3}$`. Slot `target_user` là **tùy chọn** của account (đặt lại cho người khác) — chỉ là tham số, B11 vẫn `validate_targets` qua AD (T20). **[Chốt khi hiện thực T22a]** software `device_id` dùng mẫu VPN `^[A-Z]{2,4}-\d{3,5}$`; `reason`/`version`/`justification` không có luật riêng (luật chung 100 ký tự). **T20a đổi:** `duration` `^[1-9]\d{0,2}$`; access thêm slot `action` + `target_user`, slot bắt buộc theo hành động (mục 5.1.1 P4).

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
| `existing_permission_level` (**T20a**, Q-5-8) | str ∈ {read, write, full} | Mức cao nhất trên mọi dòng quyền của đúng thư mục; không dòng → không đặt | `check_current_permissions` | nv001 + finance/public-reports `read` |

Fact VPN giữ nguyên (`device_registered`, `device_owner_is_requester`, …). Software dùng lại `device_owner_is_requester` cho máy đích (T20 gọi `check_device_registered`).

### 4.4. Bảng 20 luật [Chốt nội dung §6.3; Chốt 01/10 cho R09; Đề xuất điều kiện cụ thể]

> **Ghi chú 09/11/2026 — bản demo `lo-0811` (Q5, ĐP duyệt 09/11 10:05):** thêm **R21** `deny` · software · `install_software` · `action.facts.software_prohibited is_true` · "Phần mềm bị cấm theo quy định của công ty" (fact chỉ từ tool `check_catalog_entry.prohibited` — danh sách cấm do hệ thống ngoài giữ, `mock_services/seed.json` `prohibited_software`). Bản demo: **N4 = 21 luật, 7 allow / 12 approval_required / 2 deny**. Bản đo `bf94df2` giữ 20 luật 7/12/1 — nội dung dưới đây là của bản đo, không viết lại.

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
| R10 | allow | access | extend_permission | `other` is_false · `F.has_permission_record` is_true · `F.same_department` is_true · `F.resource_sensitivity` in [low, medium] · `F.target_user_status` in [active, probation] · `P.duration_days` lte 90 · `F.existing_permission_level` in [read, write] (**thêm ở T20a** — Q-T22a-8) | Gia hạn quyền cũ (≤ 90 ngày) vào thư mục không nhạy cảm của phòng mình |
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
backend/tests/unit/test_tool_models_p7.py           # P7 (mới) [Chốt khi hiện thực]
mock_services/tests/test_seed.py, test_admin_calls.py   # P7 [Chốt khi hiện thực]
# + 5 file test cũ của 4.7b (test_config_files, test_hrule_4b_owner, test_policy_rules_vpn, test_slots_facts, test_s0_grounding)
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

Khuôn `LUAT_C5` của `test_policy_rules_vpn.py`: gọi thẳng `evaluate_rules(rules_from_file, action, ctx, intents=…)`; **ctx dựng qua `build_ctx` từ state dựng tay** (không `RiskContext` dựng tay — f10/f11 và M-T22a-8 đòi vậy) [Chốt khi hiện thực]; mỗi ca ghi **kỳ vọng chép từ bảng 4.4**, không suy từ code. h7 hai vế: giá trị hợp lệ không ném + ngoài tập ném "ngoài tập giá trị".

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
| e15 | `duration_days` ∈ {0, −1, 400, True} | đổi | none [thêm khi hiện thực] |
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
| r1b | thêm kịch bản R07 | `_mau` | approval_required **không** bị đếm vào none [thêm khi hiện thực] |
| r4 | Không in `expected_route` ở bảng tổng | stdout | bảng tổng không chứa `expected_route`, AUTO/HITL/ESCALATE_L2, mọi `expected_route` của 3 mẫu [siết khi hiện thực] |
| r5 | Thư mục con tên bắt đầu `_` | quét đệ quy | bị bỏ (trừ khi truyền thẳng) [thêm khi hiện thực] |
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
| M-T22a-3 | R11 bỏ `license_paid is_false` | f8 (thiếu `license_paid`) |
| M-T22a-4 | R10 bỏ `duration_days lte 90` | e2, e4 |
| M-T22a-5 | R10 bỏ `same_department is_true` | e8 (ca thiếu `same_department`) |
| M-T22a-5b | R10 bỏ `target_user_status in [active, probation]` | e12b |
| M-T22a-6 | R12 đổi `deny` → `approval_required` | d6, d7, e13 |
| M-T22a-7 | R09 chỉ `grant_permission` | e6 |
| M-T22a-8 | `build_ctx` áp vế chủ máy cho mọi đích | g1, g5, a1, c1 |
| M-T22a-9 | `build_ctx` bỏ vế chủ máy | g4, f11 |
| M-T22a-10 | `fact_view` nhận `action.params` sai kiểu/ngoài khoảng | e15 (0, −1) — engine so kiểu chặt nên `"FULL"`, `1`, `"30"`, `True` không khớp dù lọt `fact_view` (lớp DSL chặn lần hai); d10/e14 giữ là ca "không ném lỗi" |
| M-T22a-11 | `rule_coverage.py` đếm `approval_required` vào "none" | r1b (+ r3) |
| M-T22a-12 | `check_facts` bỏ kiểm tập giá trị | h7 |

### 4.9. Soát bảo mật (security-reviewer, mỗi DỪNG)

Bất biến: (1) `evaluate` vẫn chỉ nhận `action, ctx` (h22); không nguồn DSL nào chứa câu người dùng — `action.params` chỉ 2 khoá danh sách trắng, giá trị đã qua `value_rules` + `build_action`; (2) không luật allow nào khớp nhờ thiếu fact (P1) — soát từng luật allow so với các luật chặt hơn cùng hành động; (3) `deny` duy nhất R12, không vào hàng đợi duyệt (B12 đã có); (4) `build_ctx` không đọc khoá state mới; (5) không intent mới nào được bật; (6) `rule_coverage.py` không ghi file ngoài `--csv`, không gọi mạng, không in `expected_route` ở bảng tổng; (7) 3 trường mới ở model tool bắt buộc, không mặc định; (8) không module nào trong `backend/app/risk/` import `app.eval`.

### 4.10. DỪNG

**Quy ước test viết trước code (mọi chặng tầng A 2 DỪNG) [Chốt khi hiện thực T22a, Q-T22a-1]:** hook pre-commit chạy toàn unit trên cây làm việc → ca chờ DỪNG 2 gom **một** hằng `CHO_DUNG2` + **một** fixture `xfail(strict=True, raises=(AssertionError, NotImplementedError))` mỗi file; DỪNG 2 gỡ hết (`grep -c xfail` = 0).


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

### 4.13. Spec cần sửa (T22a) — **đã áp ở v0.3** (13/10)

17 mục agent in ở MẪU B DỪNG 2 (`PROGRESS.md` mục T22a): mục 3–10 sửa tại chỗ (4.1 P7/P9, 4.2, 4.5, 4.7, 4.8, 4.10 — đánh dấu "[Chốt khi hiện thực]"); còn lại ở 4.14.

### 4.14. Chốt khi hiện thực T22a (`6ab716e` + `5587c78`, đẩy `2ffb005`)

| # | Chốt | Ở đâu |
|---|---|---|
| 1 | account `optional` có `target_user` (Q-T22a-3) | `slots.yaml`; B11 §4 |
| 2 | access thiếu slot `action` + slot bắt buộc theo hành động (Q-T22a-2) | **T20a P4** (5.1.1) |
| 8 | f3 và f5 cùng đầu vào (giữ cả hai — khác ý kiểm); G-GRANT ghi `has_permission_record=false` dù seed nv001 có dòng `finance/public-reports` — ca luật dựng tay, không đối chiếu seed; mẫu L1 của `rule_coverage` dùng `true` theo seed | 4.7 (ghi nhận) |
| 11 | (a) R11 an toàn nhờ vế chủ máy chỉ áp đích `device:` → ghim "`install_software` luôn `device:`"; (b) account `target == user:{requested_for}` (Q-T22a-5) | **T20a 5.1.3** bất biến (a), (b) |
| 12 | `rejection_text` ghép "cho máy …" sai với `user:`/`folder:` | **T20a P11** |
| 13 | R10 không ràng buộc mức quyền → fact `existing_permission_level` + R10 `in [read, write]` (Q-T22a-8, chốt 09/10); T24 giữ `ExtendIn` không nhận mức quyền | **T20a P1**; mục 7 |
| 14 | `decisions.md` §1.1 điều kiện R01–R15 → chốt; D-35, D-41 chữ chốt | `decisions.md` (13/10) |
| 14b | P8 §4.1 schema `gold.action`, `gold.facts`; B12 §4.2 nguồn `action.params` | Phase 6 giữ bút P8/B12 — nhờ qua tin P5→P6 #8 |
| 14c | B11 §4 quy ước `requested_for` = người bị tác động (P4) | B11 (Project) — kèm T20a P6 |
| 15 | Việc treo 19 **đóng** (h3 ghim không luật nào dùng `action.target`); Việc treo 26 → T20a b1 | `PROGRESS.md` Việc treo |
| 16 | import-linter chưa có hợp đồng `app.risk → app.eval` — giữ bằng test AST 6A + grep trước commit | ghi nhận, không đổi |
| 17 | cấp/gia hạn quyền cho người `terminated` không luật nào khớp → lớp LLM; an toàn nhờ D-38 | theo dõi Phase 6 |

---

## 5. Chặng T20 — tách T20a (đơn ý) / T20b (nhiều ý) [Chốt 10/10 — phiên PHAN-TICH-P5]

**Vì sao tách:** soát code 10/10 (`.verify/phan-tich-p5/bao-cao.md` mục 5) ước cả T20 **19–25 giờ** (bản 0.1f ghi 6–8): B5 cha/con mới có hạ tầng dữ liệu (cột `parent_ticket_id`, `child_notices`, `wake_parent`, 409 cho con) — `parent_wait`/`parent_reply_wait` còn là node **giả** (`builder.py` `_NODE_MODULES`), chưa có `b05_split`, `compose_digest`, `POST /reply`. **Bật `ENABLED_INTENTS` không làm được ở T20**: `check_plans` (`executor/plans.py:60–64`) từ chối khởi động khi intent bật thiếu `PLAN`/mẫu B18 → bật ở **T24** (Q-5-7). T24 chỉ cần T20a.

### 5.1. T20a — đơn ý cho account / software / access (tầng A + B, Opus, 2 DỪNG) [viết đủ 13/10 — soát code tại `6cf1091`] — **ĐÓNG** (`52c8349` + `03b4450`, verify G=234 xanh, CI xanh)

**Mục tiêu:** một ticket **đơn ý** thuộc `account`, `software`, `access` đi được B3 → B6 → B11 → B12 với `Action` đúng hợp đồng, fact đọc từ tool thật, luật R01–R15 quyết đúng. **Không bật** intent (T24 bật — Q-5-7); test bật bằng tiêm `enabled_intents`.
**Đầu vào:** thư mục chính ở `6cf1091` (T23a `a463150` + FE PR #35 + K2 PR #29 + KB-VPN-002…005 v2), cây sạch; KB thật đã nạp (`kb_version=3362c39b…`, 18 bài — đủ 6 `procedure_doc` bảng 4.2). **Đầu ra:** 2 commit cục bộ (mỗi DỪNG một) + phiếu push.
**Nghi thức (tầng A):** `PLAN-T20a.md` + MẪU A · **2 DỪNG** · test-writer viết bảng 5.1.6 **trước** code (`CHO_DUNG2` + `xfail(strict)` như T22a) · mutation (phần A ×2, phần B ×1) + md5 · security-reviewer mỗi DỪNG.
**Model:** Opus.

#### 5.1.0. Sự thật của code tại `6cf1091` (agent kiểm lại ở Bước 0)

| Chủ đề | Code hiện có | Hệ quả cho T20a |
|---|---|---|
| B6 | `b06_diagnose.py:64` intent ≠ `vpn` → `ValueError` (E9); gọi thẳng `tools/diagnosis/vpn.py` | Thêm 3 module chẩn đoán + bảng chọn module theo intent |
| `TOOL_MAP` | `tools/specs.py:129` kiểu `tuple[str, str, str]`, mỗi intent đúng 3 tool | D-46: đổi `tuple[str, ...]`; `access` + `check_account_status`, `software` + `check_device_registered` |
| B11 | `b11_slots.py:82–96` chỉ VPN: `vpn.target_calls`, giữ fact theo người, tính lại `DEVICE_FACTS` | Tách theo intent; 3 intent mới tính lại **toàn bộ** fact từ slot cuối |
| `build_action` | `domain/action.py:95` intent ≠ `vpn` → `ValueError` | Dựng 4 intent theo hợp đồng 5.1.3 |
| Slot | `slots.yaml` access `required: [resource_path, permission_level, duration]`, không có slot `action`; `IntentSlots` không có trường theo hành động; `MUST_APPEAR_IN_TEXT = {device_id, error_code, reason}` | P4, P5 |
| Prompt | `b03_classify` v2 không nêu tên slot/`action_hint` của 3 intent mới; `b11_extract_slots` v1 bảo "đúng chữ người dùng" — mâu thuẫn với slot enum (`permission_level` `read`, người dùng viết "quyền đọc") | P9 |
| Người duyệt | `approvers.yaml` chỉ `vpn` (`l1_01` / `l1_02` / `it_mgr01`) | P10 |
| Tin từ chối | `messages.rejection_text(action_type, device_id, …)` luôn ghép "cho máy …"; `approval_wait.py:114` truyền `params.device_id` | P11 |
| Test AST fact | `test_facts_ast.py:18` chỉ quét `tools/diagnosis/vpn.py` | Mở rộng cho mọi file `tools/diagnosis/*.py` |
| Mock | `catalog/{name}` không có → **404** (không bao giờ trả `in_catalog=false`); tên chuẩn hoá `"-".join(name.strip().lower().split())`; `resources/{path}` không có → 404; `permissions/{user}?resource_path=` lọc đúng đường dẫn (strip `/`), trả cả dòng `expired`; user lạ → 404; `account_type` user không có → 404 | Bảng 5.1.2 |
| NodeDeps | `enabled_intents` mặc định `{"vpn"}` (`graph/fakes.py:309`) | Test tiêm `frozenset({...})`; **không** sửa `fakes.py` |

#### 5.1.1. P-T20a (agent không hỏi lại)

| Mã | Chốt |
|---|---|
| **P1** | **Fact mới `existing_permission_level`** (Q-5-8, Q-T22a-8): str ∈ {read, write, full}; = mức **cao nhất** (read < write < full) trên **mọi** dòng `check_current_permissions` của đúng `resource_path` (còn hạn và hết hạn); không dòng nào → **không đặt**. `domain/facts.py` thêm vào `FACT_TYPES` + `FACT_VALUE_SETS`. **R10** thêm điều kiện `F.existing_permission_level in [read, write]` (cuối danh sách `all`; không đổi điều kiện khác, không đổi luật khác). Thiếu fact → R10 không khớp → lớp LLM. Khuôn T22a: ca thiếu fact + ca `full` + mutation |
| **P2** | **`TOOL_MAP` (D-46)** kiểu `Mapping[str, tuple[str, ...]]`: `account` 3 tool như cũ; `software` = (`check_catalog_entry`, `check_license_available`, `check_installed_list`, `check_device_registered`); `access` = (`check_current_permissions`, `check_resource_sensitivity`, `check_manager_chain`, `check_account_status`); `vpn` không đổi. `validate_specs` không đổi luật kiểm |
| **P3** | **3 module chẩn đoán** `tools/diagnosis/{account,software,access}.py` theo khuôn `vpn.py`: `TOOLS` (= `TOOL_MAP[intent]`, test ghim bằng nhau), `calls(requester_id, slots)` cho B6 (chỉ gọi tool đã đủ tham số), `target_calls(requester_id, slots)` cho B11 (đủ bộ tool của intent với slot cuối), `infer_<intent>(diag, *, requester_id, slots)` **thuần** → `(slots_suy_ra, facts)` theo bảng 5.1.2. Slot chỉ là **khoá tra cứu** (lọc dữ liệu tool); giá trị fact luôn lấy từ đầu ra tool — test AST mở rộng cho cả 4 file. `infer_*` cuối hàm `assert set(facts) <= FACT_KEYS` như VPN |
| **P4** | **Slot theo hành động (Q-T22a-2):** `IntentSlots` thêm `required_by_action: dict[str, tuple[str, ...]] = {}` (khoá ∈ `action_types`; giá trị ⊆ `optional`; sai → không khởi động). B11: `missing` = `required` thiếu + (khi đã có slot `action`) `required_by_action[action]` thiếu, theo thứ tự khai báo. `slots.yaml`: **access** `required: [action]`, `optional: [resource_path, permission_level, duration, target_user, justification]` (+ `value_rules.target_user` như account), `required_by_action: {grant_permission: [resource_path, permission_level, duration], extend_permission: [resource_path, duration]}` (`view_permissions` không cần gì thêm); **software** thêm `action` vào `optional` (để `action_hint=install_software` không bị bỏ `unknown_key`) — `build_action` lấy `install_software` khi intent chỉ có một `action_type`; **duration** đổi mẫu thành `^[1-9]\d{0,2}$` (0 ngày bị bỏ ngay ở slot — tool ghi đòi `> 0`). account, vpn không đổi |
| **P5** | **Chống LLM bịa đích (P2 của 3f mở rộng):** `domain/slots.py` `TOKEN_IN_TEXT` thêm `target_user`, `resource_path`; `PHRASE_IN_TEXT` thêm `software_name` (hằng code, không cấu hình). Lý do: ba slot này quyết **ai/cái gì bị tác động** — LLM tự điền "nv001" hay "finance/public-reports" là đổi đích hành động. `account_type`, `permission_level`, `duration`, `action` là giá trị chuẩn hoá (người dùng viết "quyền đọc", "2 tuần") → không đòi có trong câu; `value_rules` chặn ngoài tập |
| **P6** | **`requested_for` (P4 của T22a, D-41):** account, access = `slots.target_user` nếu có, không thì người gửi; software, vpn = người gửi. Lý do access có `target_user` [Đề xuất]: R12 "cấm cấp quyền cho tài khoản bị vô hiệu hoá" chỉ chạm được khi người được cấp quyền **khác** người gửi (tài khoản `disabled`/`terminated` không đăng nhập được để tự xin — `b01_identity.py:80` chặn `account_disabled`); thiếu slot này thì luật `deny` duy nhất không bao giờ khớp đầu-cuối. Xin cho người khác → `target_is_other=True` → R06/R10 không AUTO (đi duyệt/lớp LLM) |
| **P7** | **Hợp đồng `Action` theo `action_type`** — bảng 5.1.3, hằng `PARAMS_BY_ACTION` ở `domain/action.py` (một nguồn cho `build_action`, test và Phase 6 dựng danh sách trắng N1). Không slot chữ tự do (`reason`, `justification`, `version`) nào vào `params` — nợ an toàn N1 (P6→P5 #8). `extend_permission` **không** mang `permission_level` dù người dùng nêu (giữ hợp đồng `ExtendIn` — Q-T22a-8, T24 không đổi). `build_action` không có nhánh mặc định: intent lạ / thiếu slot bắt buộc theo bảng → `ValueError` (E9 — B11 đã đảm bảo đủ slot, thiếu là bug) |
| **P8** | **Tên phần mềm chuẩn hoá một nguồn:** `domain/action.py` `normalize_software_name(s) = "-".join(s.strip().lower().split())` (đúng thuật toán mock `software.normalize`); B6/B11 gọi tool bằng tên đã chuẩn hoá; `params.software_name` là tên chuẩn hoá — kết quả khớp `^[a-z0-9][a-z0-9.+#-]{0,63}$` (không dấu cách — thu hẹp đường chèn lệnh N1); không khớp → `ValueError` (không xảy ra nếu slot qua `value_rules`) |
| **P9** | **Prompt (đổi hành vi — ghi `version`):** `b03_classify` **v3**: liệt kê slot + `action_hint` hợp lệ của từng intent (bảng 5.1.4), nói rõ slot chuẩn hoá (`account_type`, `permission_level`, `duration`) được đổi về giá trị chuẩn, slot đích (`device_id`, `target_user`, `resource_path`, `software_name`) phải đúng chữ người dùng. `b11_extract_slots` **v2**: cùng quy tắc chuẩn hoá cho slot enum. Không đổi `allowed_vars`, `schema`, `role`. **Không thêm prompt id** → không thêm khoá vào 13 preset `config/scripted/*` (nhắc #8 của Phase 6 chỉ áp khi có prompt mới — có thì DỪNG hỏi). Chất lượng thật đo ở mốc G (dòng mới trong "Dồn về mốc G") |
| **P10** | **Người duyệt:** `approvers.yaml` thêm `account`, `software`, `access` cùng roster VPN (`l1_01` / `l1_02` / `it_mgr01` — Q-4-H lịch trực tĩnh, nhóm 4 người không có roster riêng theo loại) [Đề xuất]. Test B15 G5-7 / Việc treo 26: `reset_password` cho `l1_01` (người gửi `nv005`) → `targets_approver` với `l1_01` → chọn `it_mgr01`, `reason=conflict` |
| **P11** | **Tin từ chối theo đích (nợ T22a 4.7b):** `messages.py` thêm `target_phrase(action, requester_id) -> str`: `device:<id>` → "máy <id>" (mẫu `DEVICE_ID`, không khớp → "máy của bạn" — **giữ nguyên chữ VPN cũ**); `user:<id>` → `id == requester_id` ? "tài khoản của bạn" : "tài khoản <id>" (mẫu `^[a-z0-9_]{3,64}$`, không khớp → "tài khoản được yêu cầu"); `folder:<path>` → "thư mục <path>" (mẫu `resource_path`, không khớp → "thư mục được yêu cầu"). `rejection_text(action_type, target_phrase, reason_code, note)`; `approval_wait._rejected` truyền `target_phrase(action, requester)`. Test cũ `test_rejection_text.py` đổi **chữ ký gọi**, không đổi kỳ vọng chữ của ca VPN |
| **P12** | **Không** bật `ENABLED_INTENTS`; **không** sửa `executor/*`, `b17_execute.py`, `b12_assess.py`, `risk/*`, `graph/fakes.py` (NodeDeps), `builder.py`, `goto.py`, `ticket_state.py`, `llm/*`, `config/scripted/*`, file/khối M9, `.env*`, `docker-compose.yml`, `pyproject.toml`/`uv.lock`, `docs/spec/` (trừ 2 file Tuấn Anh chép vào). Không thêm luật thứ 21; luật khác R10 không đổi. Không thêm import `app.eval` vào `backend/app/risk/` |

#### 5.1.2. Chẩn đoán: tool → fact (P3) [`target_*` nói về `requested_for`]

**account** (`rf` = P6; `account_type` = slot, chưa có → `"ad"` để tra):

| Tool (tham số) | Đầu ra → fact | 404 / rỗng |
|---|---|---|
| `check_account_status(user_id=rf, account_type)` | `target_user_status` = `employment_status`; `target_is_service_account` = `is_service_account`; `target_disable_reason` = `disable_reason` (chỉ khi khác `null`); `target_account_locked` = `account.locked`; `target_lock_reason` = `account.lock_reason` khi `locked` (∈ {bad_password, admin, inactivity} giữ nguyên, giá trị khác → `"other"`, `null` → **không đặt**) | không đặt fact nào ở dòng này |
| `check_privilege_level(user_id=rf, account_type)` | `target_account_privilege` = `level` | không đặt |
| `check_lockout_history(user_id=rf)` | — (chỉ vào `diagnostics`) | — |

Không tự suy `action` cho account (khác VPN): "không đăng nhập được" có thể là đặt lại hay mở khoá — để B11 hỏi.

**software** (`rf` = người gửi; tên = `normalize_software_name(slot)`):

| Tool (tham số) | Đầu ra → fact | 404 / rỗng |
|---|---|---|
| `check_catalog_entry(software_name)` (khi có tên) | `in_catalog` = `in_catalog`; `license_paid` = `paid`; `requires_local_admin` = `requires_local_admin` | **404 → `in_catalog = False`** (mock trả 404 cho phần mềm ngoài danh mục — dữ liệu, không phải lỗi); `license_paid`, `requires_local_admin` không đặt (→ R13 bắt) |
| `check_license_available(software_name)` (khi có tên) | — (chỉ `diagnostics`; hết license là việc của T24/B17) | — |
| `check_device_registered(user_id=rf, device_id?)` | như `infer_vpn` cho máy: không nêu máy → `device_count`, `has_registered_device`, đúng 1 máy → **suy slot `device_id`**; có máy → `device_registered`, `device_owner_is_requester` | như VPN (404 → `false`) |
| `check_installed_list(device_id)` (khi có máy) | — (chỉ `diagnostics`) | — |

Hàm máy dùng chung với VPN: tách phần "máy" của `infer_vpn` thành hàm thuần `device_facts(devices, requester_id, device_id)` trong `vpn.py` (hoặc `diagnosis/_device.py`), `infer_vpn` gọi lại — **hành vi VPN không đổi** (`test_infer_vpn.py`, `test_b06_diagnose.py` xanh không sửa kỳ vọng).

**access** (`rf` = P6; `path` = slot `resource_path` đã strip `/`):

| Tool (tham số) | Đầu ra → fact | 404 / rỗng |
|---|---|---|
| `check_account_status(user_id=rf)` | `target_user_status`, `target_disable_reason` (như account); giữ `department` cho `same_department` | không đặt |
| `check_resource_sensitivity(path)` (khi có path) | `resource_sensitivity` = `sensitivity`; `same_department` = `owner_department == department` của `rf` (**chỉ khi** có cả hai) | không đặt (thư mục lạ → không luật nào khớp → lớp LLM) |
| `check_current_permissions(user_id=rf, resource_path=path?)` | khi có path: các dòng `p.path == path` → `has_permission_record` = có ≥ 1 dòng; `existing_permission_level` = mức cao nhất (P1) khi có dòng | 404 → không đặt; rỗng → `has_permission_record = False`, không đặt `existing_permission_level` |
| `check_manager_chain(user_id=rf)` | — (chỉ `diagnostics`) | — |

**Lỗi hệ thống** (sau retry/breaker) ở bất kỳ tool nào của lượt → B6: E2 `tool_system_error` (B7); B11: E2 `target_check_error` — như VPN. Lỗi hợp đồng → E9.

#### 5.1.3. Hợp đồng `Action` (P6, P7) — `PARAMS_BY_ACTION`

| `action_type` | `target` | `requested_for` | `params` (đủ, không thêm khoá) |
|---|---|---|---|
| `renew_vpn_cert`, `reissue_vpn_access`, `check_vpn_status` | `device:{device_id}` | người gửi | `device_id: str` — **không đổi** |
| `reset_password`, `unlock_account` | `user:{rf}` | `target_user` hoặc người gửi | `account_type: str` |
| `install_software` | `device:{device_id}` | người gửi | `device_id: str`, `software_name: str` (đã chuẩn hoá P8) |
| `view_permissions` | `user:{rf}` | `target_user` hoặc người gửi | `{}`, hoặc `resource_path: str` nếu người dùng nêu |
| `grant_permission` | `folder:{resource_path}` | `target_user` hoặc người gửi | `resource_path: str`, `permission_level: str`, `duration_days: int` |
| `extend_permission` | `folder:{resource_path}` | `target_user` hoặc người gửi | `resource_path: str`, `duration_days: int` (**không** `permission_level`) |

`duration` (chuỗi chữ số) → `duration_days` int. `metadata` (scope, reversible…) lấy từ `action_metadata.yaml` như cũ. **Gửi Phase 6 ở MẪU B DỪNG 1:** bảng này nguyên văn (P6→P5 #8 mục 3b — 6C dựng danh sách trắng `params` từ đây).

**Bất biến ghim bằng test (nợ T22a mục 11):** (a) `install_software` luôn `target.startswith("device:")` → vế chủ máy của `build_ctx` áp (R11 an toàn); (b) account, `view_permissions` `target == f"user:{requested_for}"`; (c) `grant`/`extend` `target == f"folder:{params['resource_path']}"`; (d) mọi `Action` dựng được: `set(params) ⊆ PARAMS_BY_ACTION[type]` và chứa đủ khoá bắt buộc; không khoá nào ∈ {`reason`, `justification`, `version`, `error_code`}.

#### 5.1.4. Slot B3 nêu cho LLM (P9 — nội dung prompt v3)

| Intent | Slot | `action_hint` hợp lệ |
|---|---|---|
| vpn | `device_id`, `error_code`, `reason` (như v2) | `renew_vpn_cert`, `reissue_vpn_access`, `check_vpn_status` |
| account | `account_type` (`ad` tài khoản đăng nhập máy/Windows, `email`, `erp`), `target_user` (mã nhân viên **người khác** nếu người dùng nêu, vd `nv005`), `reason` | `reset_password`, `unlock_account` |
| software | `software_name` (đúng chữ người dùng), `device_id`, `version`, `justification` | `install_software` |
| access | `resource_path` (đường dẫn thư mục, vd `finance/Q3`), `permission_level` (`read` = xem/đọc, `write` = ghi/sửa, `full` = toàn quyền), `duration` (số ngày, chỉ chữ số: "2 tuần" → `14`, "1 tháng" → `30`), `target_user` (mã nhân viên người được cấp quyền nếu **khác** người gửi), `justification` | `view_permissions`, `grant_permission` (quyền mới), `extend_permission` (gia hạn quyền đang/đã có) |

#### 5.1.5. Node

- **B6** (`b06_diagnose.py`): bảng `DIAGNOSERS = {"vpn": vpn, "account": account, "software": software, "access": access}` (module, cùng giao diện `calls`/`infer`); intent không có trong bảng → `ValueError` (E9) như cũ. Luồng, mã thoát, `_gather`, điểm log 2 giữ nguyên khoá; `phase` chỉ dùng 2 giá trị cũ (`"device"` khi có `device_id`, còn lại `"lookup"`) — `monitor/` không đọc trường này (grep 13/10), giữ 2 giá trị cũ để audit ổn định. Chẩn đoán ở B6 với slot chưa đủ chỉ là **gợi ý** (vào `diagnostics`, `facts` tạm cho câu hỏi B11) — B11 tính lại.
- **B11** (`b11_slots.py`): `missing` theo P4. `_build`: VPN giữ nguyên từng dòng (`vpn.target_calls`, giữ fact theo người, `DEVICE_FACTS`). 3 intent mới: `module.target_calls(requester, slots)` → `_gather` → lỗi → E2 `target_check_error` → `facts = infer(...)` (**thay toàn bộ** fact của B6 — mọi fact của 3 intent phụ thuộc slot cuối) → `build_action` → căn cứ quy trình (S0-P10, như cũ) → `S_ASSESSING`. Slot suy ra ở B11 bị **bỏ** (như VPN P6 (a)). `diagnostics_summary` không đổi.
- **B3**: không đổi code (prompt v3 qua registry). `clarify_wait`: không đổi code (prompt v2).
- **B12/B15/B16**: không đổi code; B15 dùng roster mới; `approval_wait` đổi lời gọi `rejection_text` (P11).

#### 5.1.6. Test (test-writer viết TRƯỚC code — từ bảng này, không nhìn code hiện thực)

Dữ liệu từ `mock_services/seed.json` qua bản giả đọc seed (khuôn `tests/fakes/vpn.py` → thêm `tests/fakes/seed_tools.py`: AD/phần mềm/file server trả JSON đúng như mock, 404 như mock). Mỗi ca ghi kỳ vọng chép từ 5.1.2/5.1.3 và bảng 4.4.

| # | Ca | Kỳ vọng |
|---|---|---|
| **i1** | `infer_account` nv001, `ad` | `target_account_privilege=standard_user`, `target_is_service_account=False`, `target_user_status=active`, `target_account_locked=False`; không có `target_lock_reason`, `target_disable_reason` |
| i2 | nv007 `email` (khoá `bad_password`) | `target_account_locked=True`, `target_lock_reason=bad_password` |
| i3 | `lock_reason` lạ (`"policy"`) | `other`; `lock_reason=null` khi khoá → không đặt |
| i4 | svc_backup | `target_is_service_account=True`, `target_account_privilege=admin` |
| i5 | nv004 | `target_user_status=disabled`, `target_disable_reason=security` |
| i6 | user lạ (404) | `facts == {}` |
| i7 | `target_user=nv005`, người gửi nv001 | mọi lời gọi `user_id=nv005` (đếm ở nơi nhận) |
| i8 | nv005 `account_type=erp` (seed nv005 không có tài khoản erp → 404) | không đặt fact của `check_account_status`/`check_privilege_level` |
| **s1** | `infer_software` "Zoom" + LAP-0342 (nv001) | `in_catalog=True`, `license_paid=False`, `requires_local_admin=False`, `device_registered=True`, `device_owner_is_requester=True` |
| s2 | "AutoCAD" | `license_paid=True`, `requires_local_admin=True` |
| s3 | "Photoshop" (404) | `in_catalog=False`; không `license_paid`, `requires_local_admin` |
| s4 | nv001 không nêu máy (1 máy) | suy slot `device_id=LAP-0342` + fact máy |
| s5 | nv002 không nêu máy (2 máy) | không suy; `device_count=2` |
| s6 | máy PC-0977 của nv002, người gửi nv001 | `device_owner_is_requester=False` |
| s7 | tên chưa có | không gọi catalog/license; vẫn gọi `check_device_registered` |
| **c1** | `infer_access` nv001 `finance/public-reports` | `resource_sensitivity=low`, `same_department=True`, `has_permission_record=True`, `existing_permission_level=read`, `target_user_status=active` |
| c2 | nv002 `finance/Q3` (dòng hết hạn) | `same_department=False`, `has_permission_record=True`, `existing_permission_level=read`, `resource_sensitivity=high` |
| c3 | nv001 `engineering/specs` (không dòng) | `has_permission_record=False`; **không** `existing_permission_level` |
| c4 | nhiều dòng read + full cùng path (seed tạm) | `existing_permission_level=full` (cao nhất, kể cả dòng hết hạn) |
| c5 | thư mục lạ (404) | không `resource_sensitivity`, không `same_department` |
| c6 | `/finance/Q3/` (có `/` thừa) | như `finance/Q3` |
| c7 | không có path (`view_permissions`) | không gọi `check_resource_sensitivity`; không fact theo thư mục |
| c8 | `target_user=nv004`, người gửi nv001, `engineering/specs` | lời gọi AD/quyền dùng `user_id=nv004`; `target_user_status=disabled`, `target_disable_reason=security` |
| **t1** | `TOOLS` mỗi module == `TOOL_MAP[intent]`; `validate_specs` qua | xanh |
| t2 | test AST fact (mở rộng) quét đủ 4 file `tools/diagnosis/*.py` | không phép gán `facts[...]` nào nhắc slot |
| **a1–a6** | `build_action` 6 hành động mới (bảng 5.1.3) | đúng `target`, `requested_for`, `params` từng dòng |
| a7 | account `target_user=nv005`; access grant `target_user=nv004` | `requested_for=nv005`, `target="user:nv005"`; `requested_for=nv004`, `target="folder:…"` |
| a8 | slot `justification`, `reason`, `version` có mặt | không vào `params` (cả 6 hành động) |
| a9 | extend có slot `permission_level=full` | `params` không có `permission_level` |
| a10 | software "Adobe Acrobat Pro" | `params.software_name == "adobe-acrobat-pro"` |
| a11 | VPN | `Action` giống hệt trước T20a (so với bản dựng tay) |
| a12 | intent lạ / thiếu slot bắt buộc | `ValueError` |
| a13 | bất biến (a)–(d) 5.1.3, tham số hoá mọi `action_type` của `action_metadata.yaml` | xanh — thêm `action_type` mới mà thiếu dòng `PARAMS_BY_ACTION` → đỏ |
| **p1** | `IntentSlots.required_by_action` khoá ngoài `action_types` / giá trị ngoài `optional` | lỗi schema (không khởi động) |
| p2 | B11 access `action=grant_permission`, thiếu `duration` | hỏi `duration` (E4 khi hết lượt) |
| p3 | B11 access `view_permissions` không slot khác | không hỏi — dựng `Action` |
| p4 | B11 access chưa có `action` | hỏi `action` |
| p5 | `sanitize_slots`: `target_user`/`resource_path` không có trong câu → `slot_not_in_text`; `software_name` không có (casefold) → bỏ; `permission_level=read` khi câu viết "quyền đọc" → **giữ** | đúng |
| p6 | `duration="0"` | `bad_value` |
| **n1** | B6 account/software/access (bản giả seed) | đúng bộ tool theo slot đã có; `facts` như i/s/c; `S_RETRIEVING` |
| n2 | B6 một tool lỗi 500 (sau retry) | E2 `tool_system_error`, `tool_errors` không URL |
| n3 | B11 access: B6 chạy với `finance/public-reports`, người dùng sửa thành `finance/Q3` ở lượt hỏi | fact theo `finance/Q3` (không giữ fact cũ) |
| n4 | B11 software: B6 suy máy, B11 dựng | `target="device:LAP-0342"` |
| n5 | B11 lỗi tool → E2 `target_check_error`; thiếu `procedure_doc` trong KB giả → E3 `no_procedure` (kèm `intended_action`) | đúng |
| n6 | B6/B11 VPN | toàn bộ test VPN cũ xanh **không sửa kỳ vọng** |
| **g1** | Chuỗi node B3 → B6 → B11 → B12 (ScriptedLLM, `enabled_intents` tiêm 4 intent, bản giả seed): nv001 "đặt lại mật khẩu tài khoản AD" | B12: allow / R01 |
| g2 | nv005 đặt lại cho `nv001` | không luật nào (→ lớp LLM; `DisabledEstimator` → E5) — `target_is_other=True` |
| g3 | nv001 cài Zoom (không nêu máy) | allow / R11, `target=device:LAP-0342` |
| g4 | nv001 cài AutoCAD | approval_required / R14 (all_matched R14, R15) |
| g5 | nv001 gia hạn `finance/public-reports` 30 ngày | allow / R10 |
| g6 | nv002 gia hạn `finance/Q3` 30 ngày | approval_required / R09 |
| g7 | nv001 xin `read` `finance/public-reports` 30 ngày | none (họ L1) |
| g8 | nv001 xin `read` `engineering/specs` 30 ngày cho `nv004` | deny / R12 (all_matched gồm R09 — khác phòng) |
| g9 | nv007 mở khoá email | allow / R02 |
| **r1** | R10 với `existing_permission_level` ∈ {read, write} | allow / R10 |
| r2 | `full` | none |
| r3 | thiếu `existing_permission_level` | none |
| r4 | test T22a G-EXTEND/e1/e3 cập nhật (thêm fact `read`) | xanh — ghi lý do ở MẪU B |
| **b1** | B15 `reset_password` cho `l1_01`, người gửi nv005, roster `account` | `it_mgr01`, `reason=conflict` (`targets_approver`) |
| b2 | `approvers.yaml` thật: 4 intent có roster; khởi động với `enabled_intents` 4 intent (tiêm) qua `check_approvers_config` | xanh |
| **m1** | `target_phrase`: `device:LAP-0342`, `user:<chính mình>`, `user:nv005`, `folder:finance/Q3`, chuỗi lạ | đúng chữ 5.1.1 P11; VPN giữ chữ cũ |
| m2 | B16 từ chối `grant_permission` | tin "Yêu cầu cấp quyền truy cập cho thư mục finance/Q3 chưa được duyệt. …" |
| **e1** | `test_b06_vs_mock` mở rộng: 3 intent trên mock thật (uvicorn) | fact khớp bảng i/s/c (seed khác → đỏ, báo Q) |
| h1 | `test_fact_keys_closed_list` | 20 fact (19 + `existing_permission_level`) |
| h2 | `check_policy_config`, `check_intent_config`, `check_plans` với `ENABLED_INTENTS=["vpn"]` | xanh; `ENABLED_INTENTS` mặc định vẫn `["vpn"]` |
| h3 | `b03_classify` v3, `b11_extract_slots` v2: registry nạp, `allowed_vars` không đổi; `test_llm_prompts` đếm 8 prompt | xanh |

**Test cũ được phép đổi (ghi lý do từng dòng ở MẪU B):** `test_slots_facts.py::test_fact_keys_closed_list` (19 → 20); `test_policy_rules_all.py` ca gốc G-EXTEND + e1/e3/e7–e12 (thêm fact `existing_permission_level=read`, thêm một ca "thiếu fact"); `test_rejection_text.py` (chữ ký gọi); `test_facts_ast.py` (mở rộng phạm vi); `test_config_files.py`/`test_slots_*` nếu ghim nguyên `slots.yaml`/`approvers.yaml` (giữ ý). Test cũ khác đỏ → DỪNG hỏi.

#### 5.1.7. Mutation (`scripts/mutation/mutate_t20a.py`, khuôn `mutate_t22a.py`, md5 + `git diff --stat`)

| Mã | Phá | Test phải đỏ | Lượt |
|---|---|---|---|
| M-T20a-1 | R10 bỏ điều kiện `existing_permission_level` | r2, r3 | ×2 |
| M-T20a-2 | `existing_permission_level` lấy mức **thấp nhất** | c4 | ×2 |
| M-T20a-3 | catalog 404 → không đặt `in_catalog` (thay vì `False`) | s3 | ×2 |
| M-T20a-4 | `same_department` khi thư mục 404 → `True` | c5 | ×2 |
| M-T20a-5 | `infer_account`/`infer_access` tra người gửi thay vì `rf` | i7, c8, g2, g8 | ×2 |
| M-T20a-6 | `install_software` đích `user:` | a13 (a), g3 | ×2 |
| M-T20a-7 | `build_action` bỏ `target_user` (rf luôn người gửi) | a7, g2, g8 | ×2 |
| M-T20a-8 | `params` chép mọi slot | a8, a13 (d) | ×2 |
| M-T20a-9 | extend giữ `permission_level` | a9 | ×2 |
| M-T20a-10 | `target_lock_reason` lạ → `bad_password` | i3 | ×2 |
| M-T20a-11 | B11 bỏ `required_by_action` | p2 | ×1 |
| M-T20a-12 | B11 giữ fact của B6 cho intent mới | n3 | ×1 |
| M-T20a-13 | `resource_path` bỏ khỏi `TOKEN_IN_TEXT` | p5 | ×1 |
| M-T20a-14 | `target_phrase` mọi đích → "máy …" | m1, m2 | ×1 |

Lượt 1 ở DỪNG 1 (mã có đích đã code), lượt 2 + đủ 14 ở DỪNG 2.

#### 5.1.8. Soát bảo mật (security-reviewer mỗi DỪNG, chỉ diff T20a)

(1) Fact chỉ từ đầu ra tool, slot chỉ là khoá tra (AST + đọc tay 3 module); (2) không slot chữ tự do vào `params`; `params` ⊆ `PARAMS_BY_ACTION`; (3) đích của hành động không thể do LLM bịa (P5) — `target_user`, `resource_path`, `software_name`, `device_id` đều qua `in_text`; (4) mọi 404 đi về "thiếu fact" (luật allow không khớp), không bao giờ về giá trị an toàn giả (`True`/`"standard_user"`) — riêng catalog 404 → `in_catalog=False` (chặt hơn); (5) `requested_for` account/access = người bị tác động → `targets_approver` (B15) và `target_is_other` (B12) đúng; (6) không intent nào được bật; `approvers.yaml` không làm khởi động với VPN đổi; (7) R10 chỉ thêm điều kiện, không luật nào khác đổi (`git diff config/policy.json`); (8) tin từ chối không chép chữ người dùng ngoài định danh đã qua mẫu regex; (9) không đụng file cấm P12.

#### 5.1.9. DỪNG

- **DỪNG 1 — hợp đồng + chẩn đoán (thuần):** P1 (fact + R10), P2 (`TOOL_MAP`), P3 (3 module `infer_*` + `device_facts` dùng chung), P7–P8 (`build_action` 4 intent, `PARAMS_BY_ACTION`, `normalize_software_name`), P4 phần schema (`IntentSlots.required_by_action` + `slots.yaml`), P5 (`TOKEN_IN_TEXT`/`PHRASE_IN_TEXT`). test-writer viết **toàn bộ** bảng 5.1.6 (ca của DỪNG 2 gom `CHO_DUNG2` + `xfail(strict)`); xanh: i*, s*, c*, t*, a*, p1, p5, p6, r*, h1. Mutation lượt 1 (M-T20a-1…10). security-reviewer mục 1–5, 7. `make lint` + unit. **Không cần stack** (thuần). Commit cục bộ. **MẪU B in nguyên văn bảng 5.1.3** để Tuấn Anh chuyển Phase 6.
- **DỪNG 2 — node + prompt + roster:** P4 phần B11, B6 node (P3), B11 node, P9 (2 prompt), P10 (roster), P11 (tin từ chối). Gỡ hết `xfail` (`grep -c xfail` = 0 trong file của T20a). Xanh: n*, g*, b*, m*, e1, h2, h3, p2–p4. Mutation lượt 2 (đủ 14). security-reviewer đủ 9 mục. `make verify G=234` qua phiếu stack (VPN không đổi → phải xanh như T23a; G ≠ 0 tự ingest KB fixture → stack mất KB thật — nạp lại qua phiên git **sau** commit DỪNG 2). Chạy `uv run python scripts/rule_coverage.py eval/scenarios` (D1 đã gộp, chỉ đọc, không cần stack) — in **bảng tổng** (không in `expected_route`) vào MẪU B. Commit cục bộ + phiếu push + "Spec cần sửa (T20a)" + dòng "Dồn về mốc G" (probe prompt v3/v2 với LLM thật).

#### 5.1.10. Tuấn Anh / thành viên cần biết

- Không thêm biến `.env`; `approvers.yaml` thêm 3 intent nhưng chưa bật → không đổi hành vi stack.
- **Quân (sau DỪNG 2, qua phiên git):** kịch bản D1 họ gia hạn (`extend_permission`) phải có `gold.facts.existing_permission_level` (fact mới, không phải luật — D-43 cho phép người viết kịch bản biết danh sách fact) — thiếu thì `rule_coverage` đếm vào "none". Cùng lượt sửa HB04 (license AutoCAD 3/3 đã dùng) và HB02 (`source`) đã báo 12/10.
- **Phase 6:** bảng 5.1.3 ở MẪU B DỪNG 1; số "none" của `rule_coverage` trên D1 ở MẪU B DỪNG 2.
- **M9:** T20a không đổi phân bố intent (chưa bật) — báo khi T24 bật.

#### 5.1.11. Chốt khi hiện thực T20a (MẪU B DỪNG 1 + 2, 13/10) — thay chữ ở 5.1.1–5.1.9 khi lệch

| # | Chốt | Thay chỗ |
|---|---|---|
| 1 | **Q-T20a-4 + Q-T20a-6:** `target_user` bị `sanitize_slots` bỏ (bất kỳ lý do) ở **B3** hoặc ở lượt trả lời (**`clarify_wait`**) → `ctx_flags.target_is_other=True`; **B6 giữ cờ** (không ghi đè, mọi nhánh); prompt v3 dặn "làm cho người khác → luôn điền `target_user`". Lý do: "reset mật khẩu cho Nguyễn Văn A" từng chạy R01 trên **chính người gửi**. Test g10, g11, n7; mutation M-T20a-15…17 | 5.1.5 ("B3/`clarify_wait` không đổi code") |
| 2 | `DIAGNOSERS` (`tools/diagnosis/__init__.py`) chỉ 3 intent mới; VPN giữ nhánh cũ (chữ ký `vpn.calls` khác, test cũ ghim) | 5.1.5 |
| 3 | `build_action` thêm `_check_params` (kiểm lại theo `PARAMS_BY_ACTION`); `IntentSlots.missing()`; `requested_for_of()` một nguồn; VPN thiếu `device_id` → `ValueError` (thay `KeyError`, cùng E9) | 5.1.1 P7, P4 |
| 4 | `duration` `^[1-9][0-9]{0,2}$` (không `\d` — chữ số Unicode); `resource_path` chặn đoạn `.`/`..` | 5.1.1 P4; 4.2 |
| 5 | Q-T20a-5: g8 kiểm `requested_for == "nv004"` | 5.1.6 g8 |
| 6 | Mutation đủ **17** mã (M-T20a-15 B6 ghi đè cờ, -16 B3 không đặt cờ, -17 `clarify_wait` không đặt cờ) | 5.1.7 |
| 7 | `rule_coverage` D1: 40 kịch bản → allow 13 / approval 13 / deny 0 / **none 14** (HB01, HB03) | 5.1.9 |
| **Nợ (không chặn)** | A12 `clarify_wait` chỉ nhận slot đang thiếu (nợ UX — **không** thuộc T20b, để sau cổng 5); biên token `\w` nhận giá trị bị cắt ngắn (NGHI b); `device_id`/`DEVICE_ID` vẫn `\d` (Q-T20a-7 = B); N3 LLM tự điền slot chuẩn hoá → AUTO không hỏi lại (trong quyền tự làm, ≤ 90 ngày); N5 quy tắc "người khác" áp cả VPN (chặt hơn — chạy lại ở mốc G); N7 tin từ chối thiếu `requester_context` (chỉ chữ); N8 `same_department` hai chuỗi rỗng → **sửa ở T24 P9**; test AST không theo luồng điều khiển; G-EXTEND dựng tay giữ `permission_level` | — |
| **Chuyển Quân** | R11 không đòi `device_registered` (luật T22a) — soát "giữ/thêm" | — |

### 5.2. T20b — nhiều ý: B5 tách ticket con + vòng ticket cha + `POST /reply` (tầng A, Opus, 2 DỪNG) [viết đủ 13/10 — soát code tại `90ee85d`] — **ĐÓNG** (`14316ad` + `5df24c7` + `8a7c697`, verify xanh, đẩy 14/10)

**Mục tiêu:** câu có ≥ 2 ý đi được đầu-cuối trên stack: B3 phán từng ý → B5 tạo ticket con (mỗi ý một thread, một `Action`, M5 đánh giá riêng) → con chạy từ **B6** → con không nhắn người dùng mà để lại notice → cha gửi **một** tin tổng hợp mỗi lượt người dùng → người dùng trả lời **một lần** cho mọi ý qua `POST /api/tickets/{cha}/reply` → cha chuyển từng phần xuống đúng con → cha đóng theo bảng 6 trường hợp (D-17, D-18, D-29, D-30, D-31).
**Đầu vào:** thư mục chính ở `90ee85d` (T24 `457239d` + PR #38 M9 A4, migration `0009`), cây sạch, KB thật đã nạp, 4 intent bật. **Đầu ra:** 2 commit cục bộ (mỗi DỪNG một) + phiếu push. **Không migration** (bảng/cột/CHECK đã có từ `0001`/`0007`).
**Nghi thức (tầng A):** `PLAN-T20b.md` + MẪU A · **2 DỪNG** · test-writer viết bảng 5.2.8 **trước** code (`CHO_DUNG2` + `xfail(strict)`) · mutation (phần A ×2) + md5 · security-reviewer mỗi DỪNG. Đụng file lõi (`runner.py`, `late_event.py`, `effects`/`db/runtime.py`, `parent_wait`, `ticket_state`) → **không giao subagent** phần code (test-writer chỉ viết test từ bảng). **Model:** Opus.
**Chốt của Tuấn Anh (13/10):** **Q5 = con vào thẳng B6** (seed từ kết quả B3 của cha — B03 §5.3, P1 §8; không chạy lại B1/B2/B3); **ý lẫn = tách**, ý ngoài phạm vi / không chắc / chưa bật thành ticket con đóng ngay E1 (không bỏ sót phần nào, khớp TC32).

#### 5.2.0. Sự thật của code tại `90ee85d` (agent kiểm lại ở Bước 0)

| Chủ đề | Code hiện có | Hệ quả cho T20b |
|---|---|---|
| DB | `tickets.parent_ticket_id` (FK), `is_parent`, `aggregate_status` (CHECK 6 giá trị B03 §5.4); `child_notices` (`kind` ∈ answer/question/result/rejection/escalation, `needs` ∈ none/answer/confirm, `effect_key` UNIQUE, cặp `delivered_round`/`delivered_at`, chỉ mục `pending`); `side_effects.kind` có `child_create`, `child_submit`, `child_event`; `tickets` **không** append-only (B20 `finalize_once` UPDATE) | **Không migration.** Agent kiểm `child_notices` không thuộc `APPEND_ONLY` (cần UPDATE `delivered_*`) — thuộc thì DỪNG hỏi |
| State | `TicketState`: `parent_ticket_id`, `is_parent`, `children`, `parent_round`, `awaiting` | Thêm đúng **1** khoá `child_seeds` (P3) — `check_state_keys` chặn khoá lạ |
| Chuyển trạng thái | `states.PARENT_ONLY` (quy tắc 3 D-29): `CLASSIFYING↔CONFIRMING`, `CLASSIFYING/CONFIRMING → RESOLVED/REJECTED/ESCALATED` khi `is_parent`; `(S_CLASSIFYING, S_CLASSIFYING)` có trong bảng 2.1 | Không sửa `states.py` |
| Routing | `b03_classify → {b06_diagnose, parent_wait}`; `parent_wait → {parent_wait, parent_reply_wait}`; `parent_reply_wait → {parent_wait}`; cả hai trong `WAIT_NODES` (B5) | Không sửa `routing.py` |
| Node cha | `parent_wait.py`, `parent_reply_wait.py` là node **GIẢ** (đọc `deps.scenario`); `builder._NODE_MODULES` dùng chung cho đường giả và thật, `REAL_NODE_MODULES` không ghi đè | Viết bản thật; bản giả chuyển sang `graph/nodes/fake/` (khuôn 3-Q32 cách A) để `make gate2` giữ nguyên |
| B3 | `b03_classify.py:98` — `len(out.intents) >= 2` → E1 `multi_intent_not_enabled` (đếm MỌI ý, kể cả ngoài phạm vi — Q-3f-6) | Thay bằng phán ý + B5 (P2) |
| Runner | `submit(parent_ticket_id=)`; `after_turn` chỉ đánh thức cha khi thread con **kết thúc**; `wake_parent` chỉ resume khi `snap.next == ("parent_wait",)`; `_run_initial` dựng state từ dòng `tickets` rồi chạy từ `ENTRY` (B1); `_divert_bound(seed=True)` đã có khuôn `aupdate_state(as_node=…)` + `ainvoke(None)` | P4, P6 |
| Notifier | `wiring.py:222` `LoggingNotifier()` (noop) — tin nằm trong `conversation` của checkpoint; `notify_user` đi qua `effects.once` ở B10 (`confirm`), B11 (`answer`), B16 (`none`), B18 (`confirm`), B20 (`none`); `run_once` đặt `_TX` (contextvar) cho hàm side effect | P5 |
| Hạn chờ | B10/B11/B17 đặt `deadlines.set` (24 h / 48 h) qua `effects.once`; `worker_jobs.expected_status`: cha → `S_CONFIRMING` (đã có) | Con **không** đặt hạn (P5) |
| API | `_owned_leaf`: ticket con → 409 "Vui lòng trả lời trong hội thoại chung"; `WAITING_FOR` có `parent_reply_wait → "reply"`; **chưa** có route `/reply`; `late_event.WAITS["parent_reply_wait"] = (S_CONFIRMING, "B5", {reply, timeout})` | P11 |
| B20 / audit | `audit/final.resolution_path`: cha → NULL; `b20_audit`: không escalation/tin cho cha (`if code and not is_parent`) | Không sửa |
| ScriptedLLM | `SqlPresetResolver`: thẻ `[fake:…]` từ `tickets.redacted_request` của ticket đang chạy — con (`span`, không thẻ) → `default` | P13 |
| Mã thoát | `domain/exit_codes.REASON_DETAILS` (test AST quét mọi chuỗi gán `escalation_reason_detail`) | Thêm `split_span_invalid` (P2) |
| Nhãn | `messages.ACTION_LABELS` (:221) | Tiêu đề ý (P9) |

#### 5.2.1. P-T20b (agent không hỏi lại)

| Mã | Chốt |
|---|---|
| **P1** | **Q5 [Chốt 13/10]:** con bắt đầu ở **B6** với intent + slot từ phần tử `IntentItem` của cha (bảng 5.2.3); con **không** chạy B1/B2/B3 (B1 đã xác lập danh tính, B2 đã sàng lọc **cả câu** — `span` là đoạn con của câu đã sàng lọc). Hệ quả: con không bao giờ `S_BLOCKED`; con không tự tách tiếp; một lần LLM B3 cho cả câu |
| **P2** | **Phán ý (B3 → B5) [Chốt 13/10 "ý lẫn = tách"]:** bảng 5.2.2. `len(intents) == 1` → đường đơn ý hiện có (**không đổi một dòng**). `len(intents) ≥ 2` và **≥ 1 ý chạy được** → tách **mọi** ý (ý không chạy được thành con đóng ngay E1 với `reason_detail` của ý đó). `≥ 2` mà **0 ý chạy được** → cả câu E1 như hiện nay (không tạo con): không ý nào trong phạm vi → `out_of_scope`; còn lại → `reason_detail` của ý đầu theo thứ tự kiểm cũ. Thứ tự ý = thứ tự LLM trả (= `index` 1..n) |
| **P3** | **B5 hai pha (D-18, seed bền trước khi con chạy):** (a) trong `b03_classify` (bước B5): mỗi ý `effects.once("child_create", tickets.create_child, …, step="B5", sub=cid)` (dòng `tickets` con, **không** dòng `turns`); `tickets.mark_parent_once(cha)` (UPDATE `is_parent=true` chỉ khi đang false, idempotent); `goto(S_CLASSIFYING, next_node="parent_wait", step="B5", event=f"split_into_{n}_children", is_parent=True, children=[…], child_seeds={cid: seed}, reasoning_loops=loops)`. (b) `parent_wait` mỗi lần chạy **khởi động** mọi con chưa có thread (P4) **trước** khi đối soát. Không con nào chạy trước khi checkpoint của cha có `child_seeds` |
| **P4** | **Khởi động con (`ChildOps.start`, ở tầng runner, không qua NodeDeps):** `cid = f"{cha}-{i}"` (tất định). Dưới khoá con: thread đã có state → bỏ qua (đã khởi động); chưa → mở lượt `turns(event_type="submit")` → `aupdate_state(cfg, seed_state + goto(...), as_node="b03_classify")` (khuôn `_divert_bound(seed=True)`; `goto` từ `S_CLASSIFYING` → `S_DIAGNOSING`/`next=b06_diagnose`, `event="child_started"`, hoặc → `S_ESCALATED`/`next=b20_audit`/E1, `event="child_not_runnable"`, `step="B5"`) → `ainvoke(None)` **lồng** (không lấy thêm `Semaphore`, không gọi `after_turn` — cha tự đối soát ngay sau) → đóng lượt. Ghi `effects.once("child_submit", sub=cid)` **sau** khi chạy (peek trước: đã có → bỏ). `recover`/`run_new` gặp ticket con **chưa có thread** → đóng lượt, trả `None` (khởi động là việc của cha — một đường code). `ChildOps` dựng trong `Runner` (import cục bộ), đưa vào `RunContext` (`current_run().children`) → **không sửa `wiring.py`/`fakes.py` cho phần này** |
| **P5** | **Con không nhắn, không đặt hạn (D-31) — chỉ đổi tầng hạ tầng, logic nhánh giữ nguyên:** (a) `notify/` thêm `ChildAwareNotifier` (thay `LoggingNotifier` ở `wiring.py:222` — **dòng duy nhất** T20b sửa trong `wiring.py`): trong transaction của `effects.once` (`current_tx()`), đọc `parent_ticket_id` của `ticket_id`; ticket thường/cha → như cũ (`noop:…`); ticket con → INSERT `child_notices(parent, child, source_step, kind, needs, body=text, effect_key)` → trả `notice:<id>`. `source_step` + `effect_key` lấy từ contextvar mới mà `run_once` đặt cùng `_TX` (`db/runtime.py`); `kind` theo bước: B10 → `answer`, B11 → `question`, B16 → `rejection`, B18 → `result`, B20 → `escalation` (bước khác → `ValueError` = E9, thấy được). (b) `SqlDeadlineStore.set` cho ticket con → không ghi, trả `child:skip` (hạn do cha giữ). (c) Tin của con **vẫn** vào `conversation` của checkpoint con (nội bộ, không ai hiển thị) — không sửa B10/B11/B16/B17/B18/B20 |
| **P6** | **Đánh thức cha:** `Runner.after_turn` của ticket con gọi `wake_parent` khi thread con **kết thúc** hoặc **dừng ở `clarify_wait`/`confirm_wait`** (P1 §6.1); không đánh thức khi dừng ở `approval_wait`. Lượt con chạy lồng từ cha (P4, P8) không gọi `after_turn` (cha đang giữ khoá cha — tránh deadlock 2b-Q7) |
| **P7** | **`parent_wait` thật** (mã giả 5.2.4): khởi động con thiếu (P4) → `children_view` từ **DB** (D-17: `tickets.final_state` + `child_notices` chưa gửi; không đọc checkpoint con) → chưa đủ con dừng → `interrupt` rồi `goto` quay lại chính node → đủ → vòng `rnd = parent_round + 1`, `compose_digest` (P9) → `effects.once("notify_user", …, sub=f"round:{rnd}")`, trong **cùng** transaction đánh dấu `delivered_round=rnd` cho đúng các notice vừa gom → mọi con đã kết thúc: `aggregate_children` (P10) → `goto(final, next_node="b20_audit", event="children_aggregated", aggregate_status=…)`; còn ý chờ người dùng: hạn `clarify` (có ít nhất một `needs=answer`, 24 h) hoặc `confirm` (48 h) qua `effects.once("deadline_set", sub=f"round:{rnd}")` → `goto(S_CONFIRMING, next_node="parent_reply_wait", event="digest_sent", awaiting={cid: needs})`. Tin tổng hợp vào `conversation` của **cha** (FE đọc) |
| **P8** | **`parent_reply_wait` thật:** `interrupt` → sự kiện `reply` (`items`) hoặc `timeout` → với từng `cid` trong `awaiting` (thứ tự `index`): `payload` = timeout → `{"kind":"timeout"}`; `needs=answer` → `{"kind":"user_reply","text":answer}`; `needs=confirm` → `{"kind":"confirmed"/"unresolved","note":…}` → `peek("child_event", sub=f"{cid}:{rnd}")` có → bỏ; chưa → `ChildOps.deliver(cid, expected, payload)` → `effects.once("child_event", sub=f"{cid}:{rnd}")` ghi lại. `deliver` dưới khoá con: con đúng trạng thái + đúng node chờ (`answer` → `S_CLARIFYING`/`clarify_wait`, `confirm` → `S_CONFIRMING`/`confirm_wait`) → `resume_locked` **lồng** (không `after_turn`); lệch → **bỏ qua, không `late_event`** (đã giao ở lần chạy trước mà LangGraph đã ghi giá trị resume, hoặc con đã đi tiếp) — ghi tên con vào `audit_detail.skipped`; `TicketBusy` → thử lại 1 s × 5 rồi ném (E9 cha — hiếm). Ghi **một** tin người dùng vào `conversation` của cha (đã che, ghép theo thứ tự ý: "Ý 1: Đã ổn · Ý 2: <câu trả lời>", "Chưa ổn — <ghi chú>") — hợp đồng FE (d). `goto(S_CLASSIFYING, next_node="parent_wait", event="reply_dispatched" | "reply_timeout")` |
| **P9** | **`compose_digest` thuần, theo mẫu, không LLM:** mỗi ý một khối theo `index`; tiêu đề = `ACTION_LABELS[seed.slots.action]` nếu có, không thì nhãn loại yêu cầu (`account` "Tài khoản", `vpn` "VPN", `software` "Phần mềm", `access` "Quyền truy cập", ý E1 "Yêu cầu khác") — **không** để LLM đặt (chốt 10/10 (a)); thân = `body` của notice (đã là chữ mẫu/đã qua output guard ở node con); ý đã gửi ở vòng trước và chưa có notice mới thì không lặp lại. Vòng cuối không còn notice nào → chỉ câu tổng kết theo `aggregate_status` (bảng 5.2.5). Hình dạng tin: hợp đồng FE 5.2.6 |
| **P10** | **`aggregate_children` thuần** — bảng 5.2.5 (6 trường hợp [Chốt B5] + tổ hợp đủ 3 loại [Đề xuất]); ưu tiên ESCALATED > REJECTED > RESOLVED; chỉ gọi khi mọi con có `final_state`. Cha: không `exit_code`, `close_reason=NULL`, không `escalations` (D-30 — `b20_audit`/`audit/final` đã đúng, test ghim) |
| **P11** | **API** (bảng 5.2.6): `POST /api/tickets/{cha}/reply` + `GET /api/tickets/{cha}` thêm `children_progress`. Kiểm `items` khớp **đúng** `awaiting` (thiếu/thừa → 422) **dưới khoá cha**, sau guard: `start_event` thêm tham số tuỳ chọn `validate(snapshot)` gọi sau `_guard` (ném `InvalidReply` → 422, nhả khoá như các nhánh từ chối khác) |
| **P12** | **Lưới an toàn ở worker** (`worker_jobs.scan_parents`, mỗi `PARENT_RECONCILE_INTERVAL=60s`, lịch trong `schedule_jobs` — **ngoài khối M9**): chỉ đọc DB (worker không đọc checkpoint): (a) cha `final_state IS NULL` mà mọi con đã dừng theo DB **hoặc** có con chưa có dòng `turns` (chưa khởi động) → `runner.wake_parent` (no-op nếu cha không ở `parent_wait`); (b) con `final_state IS NULL` có notice `needs≠none` mà cha đã có `final_state` → `deliver_event(con, …, {"kind":"timeout"}, source="worker")` — con không bao giờ treo vì cha lỗi (P1 §8.2) |
| **P13** | **ScriptedLLM cho con trên stack:** `SqlPresetResolver` — ticket con không có thẻ → lấy thẻ của **cha** + hậu tố `-<i>` (`[fake:tc34]` → preset `tc34-1`, `tc34-2`); preset con thiếu → `ScriptExhausted` (E9 thấy được, như cũ). Chỉ `llm/providers/scripted.py` (dev/test), không đụng gateway |
| **P14** | **Không** sửa: `b12_assess.py`, `b17_execute.py`, `risk/*`, `config/policy.json`, `settings.py`, `audit/check.py`, `graph/fakes.py` (NodeDeps), `executor/*`, `tools/*`, `domain/action.py`, `domain/facts.py`, `domain/slots.py`, `domain/states.py`, `graph/routing.py`, `config/prompts/*` (b03 v3 đã dặn tách ý + `span`), khoá `b14_*` của preset, `llm/*` ngoài `providers/scripted.py`, migration, M9 (`monitor/*`, khối `# M9`, `worker.py` khối M9, `.importlinter`), `docker-compose.yml`, `.env*`, `pyproject.toml`/`uv.lock`, `kb/*`, `eval/scenarios/*`. `wiring.py`: **chỉ** dòng notifier (P5) — đã báo Phase 6 (6C cũng sửa `wiring.py`, khác dòng). Sửa được (agent chính): `b03_classify.py` (nhánh ≥ 2 ý), `parent_wait.py`, `parent_reply_wait.py`, `graph/nodes/fake/*` (chuyển bản giả), `builder.py` (bảng node), `runner.py`, `graph/context.py`, `late_event.py` (`validate`), `db/tickets.py`, `db/runtime.py`, `graph/ports.py`, `notify/*`, `domain/ticket_state.py` (khoá `child_seeds`), `domain/exit_codes.py` (`split_span_invalid`), `domain/messages.py` (digest), `api/tickets.py`, `worker_jobs.py` + `worker.py` (dòng lịch ngoài M9), `llm/providers/scripted.py`, `config/scripted/*` (preset mới), `tests/stack/gate5.py`, `Makefile`/`verify.sh` nếu cần |

#### 5.2.2. Phán từng ý (P2) — thứ tự kiểm cố định, mỗi ý đúng một kết quả

| # | Điều kiện của ý (theo thứ tự) | Kết quả của con | `reason_detail` |
|---|---|---|---|
| 1 | `type == "out_of_scope"` | E1 ngay | `out_of_scope` |
| 2 | `span` rỗng hoặc **không** là đoạn con của câu (`phrase_in_text`) | E1 ngay; `redacted_request` của con = **cả câu** (L2 đọc được) | `split_span_invalid` (mới) |
| 3 | `confidence < TAU_INTENT` | E1 ngay | `intent_low_confidence` |
| 4 | `type ∉ enabled_intents` | E1 ngay | `intent_not_enabled` |
| 5 | còn lại | **chạy được** → B6 | — |

Ý chạy được: `slots, dropped = sanitize_slots(spec, raw, text=span)` (cửa duy nhất — `text` là **span của ý**, không phải cả câu: slot của ý này phải nằm trong đoạn của chính nó); `target_user` bị bỏ → `ctx_flags.target_is_other=True` của con (Q-T20a-4 áp từng con). Điểm log 1 của cha: như hiện nay + `is_multi`, `children` (số), `verdicts` (danh sách mã kết quả theo `index`) — không câu, không giá trị slot.

#### 5.2.3. Seed của con (P1, P3, P4)

| Khoá state con | Giá trị |
|---|---|
| `ticket_id` / `parent_ticket_id` | `f"{cha}-{i}"` / `cha` |
| `session_id`, `requester_context` | chép từ cha (bản frozen của B1) |
| `redacted_request` | `span` của ý (ý #2 bảng 5.2.2: cả câu) — cũng là cột `tickets.redacted_request` của dòng con (`create_child`) |
| `status` trước `goto` | `S_CLASSIFYING` (để `goto` ghi đúng chuyển `CLASSIFYING → DIAGNOSING` / `→ ESCALATED`) |
| `intent`, `intent_confidence`, `span` | từ `IntentItem` (ý E1 #1: không đặt `intent`) |
| `slots`, `facts`, `ctx_flags` | slot đã sanitize (5.2.2), `facts={}` (B3/B5 **không bao giờ** ghi fact — G-01), cờ theo ý |
| `conversation`, `clarification_turns`, `off_topic_streak`, `reasoning_loops`, `is_parent`, `children` | `[]`, `0`, `0`, `loops` của cha, `False`, `[]` |
| E1 (ý #1–#4) | thêm `exit_code="E1"`, `escalation_reason_detail` theo bảng 5.2.2 → B20 của con ghi `escalations` + notice `escalation` (mẫu E1 7.1) |

`child_seeds[cid]` (trong state cha) = các giá trị trên **trừ** `requester_context` (đọc lại từ state cha lúc khởi động) — không câu nào khác ngoài `span`.

#### 5.2.4. Vòng của cha (P7, P8) — mã giả chốt

```python
async def parent_wait(state):                                   # S_CLASSIFYING (cha)
    await children.start_missing(state)                         # P4 — idempotent, trước đối soát
    view = await tickets.children_view(state["children"])       # DB: final_state + notice chưa gửi (D-17)
    # stopped(c) = c.final is not None or any(n.needs != "none" for n in c.pending)
    if not all(stopped(c) for c in view):
        interrupt({"wait": "children"})
        return await goto(state, S_CLASSIFYING, next_node="parent_wait", step="B5", event="parent_woken")
    rnd = (state.get("parent_round") or 0) + 1
    digest = compose_digest(view, seeds=state["child_seeds"], round=rnd)        # thuần (P9)
    await effects.once(state, "notify_user", notices.deliver_round, state["ticket_id"], digest,
                       step="B5", sub=f"round:{rnd}")          # đánh dấu delivered_round CÙNG transaction
    if all(c.final for c in view):
        final, agg = aggregate_children(view)                  # P10
        return await goto(state, final, next_node="b20_audit", step="B5", event="children_aggregated",
                          aggregate_status=agg, parent_round=rnd, conversation=[digest_msg(digest)])
    kind = "clarify" if any(n.needs == "answer" for c in view for n in c.pending) else "confirm"
    await effects.once(state, "deadline_set", deadlines.set, state["ticket_id"], kind, deadline_of(kind),
                       run.turn_id, step="B5", sub=f"round:{rnd}")
    return await goto(state, S_CONFIRMING, next_node="parent_reply_wait", step="B5", event="digest_sent",
                      parent_round=rnd, awaiting={c.id: c.needs for c in view if not c.final},
                      conversation=[digest_msg(digest)])
```

`c.needs` của con chưa kết thúc = `needs` của notice **mới nhất** chưa gửi (một con dừng ở một điểm chờ một lúc). Con ở `approval_wait` (không notice `needs≠none` chưa gửi, chưa `final`) = **chưa dừng** (D-31: chờ L1 không phải điểm dừng). Hạn: `CLARIFY_TIMEOUT` / `CONFIRM_TIMEOUT` của `policy.json` (không hằng mới).

#### 5.2.5. Đóng cha (P10) và câu tổng kết (P9)

| Kết quả các con | Cha | `aggregate_status` | Câu tổng kết (vòng cuối) |
|---|---|---|---|
| Tất cả RESOLVED | `S_RESOLVED` | `ALL_RESOLVED` | "Cả {n} yêu cầu đã hoàn tất." |
| ≥ 1 ESCALATED, còn lại RESOLVED | `S_RESOLVED` | `PARTIALLY_ESCALATED` | "Đã xong {r}/{n} yêu cầu; phần còn lại đã chuyển kỹ thuật viên." |
| Tất cả ESCALATED | `S_ESCALATED` | `ALL_ESCALATED` | "Các yêu cầu đã được chuyển kỹ thuật viên." |
| ≥ 1 REJECTED, còn lại RESOLVED | `S_RESOLVED` | `PARTIALLY_REJECTED` | "Đã xong {r}/{n} yêu cầu; có yêu cầu không được duyệt." |
| Tất cả REJECTED | `S_REJECTED` | `ALL_REJECTED` | "Các yêu cầu không được duyệt." |
| ESCALATED + REJECTED, không RESOLVED | `S_ESCALATED` | `MIXED` | "Các yêu cầu không xử lý tự động được (chuyển kỹ thuật viên hoặc không được duyệt)." |
| **[Đề xuất]** đủ cả 3 loại (≥ 1 mỗi loại) | `S_RESOLVED` | `PARTIALLY_ESCALATED` | như dòng 2 — có RESOLVED nên cha RESOLVED; ESCALATED > REJECTED nên nhãn `PARTIALLY_ESCALATED` (cổng 5 "tổ hợp có cả 3 loại") |

Con `S_BLOCKED` không xảy ra (P1) — gặp → `ValueError` (E9 cha, thấy được). Câu tổng kết thuần mẫu, `{n}`, `{r}` là số.

#### 5.2.6. Hợp đồng API + FE (P11 — 4 điểm chốt 10/10, `claude/viec-cho-phase5.md` mục 5)

- **Tin tổng hợp** trong `conversation` của cha: `{role:"assistant", kind:"digest", round, text, items:[{child_id, index, title, kind, text, needs}]}` — `kind` của item = `kind` notice (`answer` hiển thị như `result`: FE nhận `result|question|rejection|escalation` → B10 `answer` map sang `result`); `text` (cấp tin) = các khối nối "Ý {index} – {title}: {text}" + câu tổng kết nếu có. `options`, `sources`: **chưa phát** (giữ trường trong kiểu FE — chốt (b); nợ: nguồn trích của B10 con chưa vào digest).
- **`GET /api/tickets/{cha}`** thêm `children_progress: [{child_id, index, title, progress, outcome}] | null` (ticket thường → `null`): con có `final_state` → `closed` + `outcome` (`resolved`/`escalated`/`rejected`); con có phiếu duyệt `pending` → `pending_approval`; con có notice chưa gửi `needs≠none` → `ready`; con chờ người dùng sau khi tin đã gửi (cha ở `parent_reply_wait`, con ∈ `awaiting`) → `needs_user`; còn lại → `processing`. Chỉ từ DB + checkpoint **cha** (không đọc checkpoint con).
- **`POST /api/tickets/{cha}/reply`** (quyền `ticket:message`, chủ ticket): body `{items: {[child_id]: {answer: str 1..4000} | {confirmed: bool, note?: str ≤ 1000}}}`, `extra="forbid"` mọi tầng. Thứ tự kiểm (khuôn `/messages`): 413 → quyền → 404 → 403 (không phải chủ) → 409 `CHILD_MESSAGE` (gọi vào ticket con) → 422 hình dạng body → privacy guard từng `answer`/`note` (503 khi guard lỗi; bí mật → `privacy_secret_redacted`) → `start_event(cha, S_CONFIRMING, {"kind":"reply","items":…}, validate=…)`: không ở `parent_reply_wait` → 409 `LateEvent`; `items` ≠ đúng tập `awaiting` (thiếu, thừa, sai loại so với `needs`) → 422 `{error:"invalid_request", fields:["body.items.<child_id>"]}` (chốt (c) — chặt). 202 `{ticket_id, status, notices}`.
- Tin người dùng ghép (chốt (d)) do **node** ghi (P8), không do route.
- Ticket con: `/messages`, `/confirm` → 409 (đã có, test ghim); `/reply` lên con → 409 `CHILD_MESSAGE`; `/reply` lên ticket thường → 409 `LateEvent` (không ở `parent_reply_wait`).

#### 5.2.7. `make gate5` thêm kịch bản nhiều ý (preset `tcNN` cho cha + `tcNN-<i>` cho từng con)

| Mã | Người gửi · câu | Kỳ vọng |
|---|---|---|
| tc12 / tc34 | nv001 "đặt lại mật khẩu tài khoản AD giúp mình, tiện cài luôn Adobe Acrobat Pro" | 2 con. Con 1 R01 AUTO → reset 1 lần → dừng `confirm_wait`. Con 2 R14 → phiếu → **0 tin** tới cha trước khi duyệt (đếm `conversation` cha) → duyệt → assign + install → dừng. Cha: **1** tin digest 2 khối `result` → `/reply` cả hai "Đã ổn" → 2 con `resolved_user_confirmed` → tin tổng kết → cha `S_RESOLVED`/`ALL_RESOLVED`, `close_reason IS NULL`, `exit_code IS NULL`. **Số tin assistant của cha = số lượt người dùng (2)** |
| tc35 | nv001 "đặt lại mật khẩu AD và gia hạn quyền thư mục finance/public-reports" (thiếu `duration`) | Digest vòng 1: `result` + `question` → `/reply` {ý 1 confirmed, ý 2 answer "30"} → con 2 B11 → R10 AUTO → extend 1 lần → dừng → digest vòng 2 (`result` ý 2) → `/reply` {ý 2 confirmed} → `ALL_RESOLVED`; số tin assistant cha = 3 = số lượt người dùng |
| tc36 | như tc34 nhưng trả lời {ý 1 "Chưa ổn" + ghi chú, ý 2 "Đã ổn"} | con 1 E8, con 2 `resolved_user_confirmed`; cha `S_RESOLVED`/`PARTIALLY_ESCALATED`, `close_reason NULL`; 1 dòng `escalations` (con 1), 0 cho cha |
| tc32 | nv001 "đặt lại mật khẩu AD, tiện sửa máy in tầng 3 giúp mình" | con 2 E1 `out_of_scope` ngay (không B6); digest vòng 1: `result` (ý 1) + `escalation` (ý 2) → `/reply` {ý 1 confirmed} → cha `PARTIALLY_ESCALATED` |
| tc12r | như tc34, L1 **từ chối** ý 2 | con 2 `S_REJECTED` (notice `rejection`, `needs=none`) → digest: `result` + `rejection` → `/reply` {ý 1} → cha `S_RESOLVED`/`PARTIALLY_REJECTED`; 0 lời gọi ghi cho ý 2 |

License Adobe Acrobat Pro dùng chung với tc21b — đặt lại dữ liệu mock trước mỗi kịch bản theo khuôn gate5 (hết license → con 2 E7, không phải lỗi T20b). Mỗi kịch bản thêm: `/messages`, `/confirm` lên con → 409; `/reply` thiếu/thừa ý → 422 và **không** con nào nhận sự kiện; audit đủ điểm log của từng con; `GET` cha có `children_progress` đúng ở từng mốc (ít nhất: `pending_approval` lúc chờ duyệt, `ready`/`needs_user` sau digest, `closed` cuối).

#### 5.2.8. Test (test-writer viết TRƯỚC code — từ bảng này, không nhìn code hiện thực)

| # | Ca | Kỳ vọng |
|---|---|---|
| **v1** | Phán ý: 2 ý trong phạm vi chạy được | 2 con, cả hai `child_started` → B6; `children == [cha-1, cha-2]` |
| v2 | 1 ý trong phạm vi + 1 `out_of_scope` | tách; con 2 E1 `out_of_scope`, không chạy B6 |
| v3 | 2 ý, cả hai `out_of_scope` | **không** tách; cả câu E1 `out_of_scope` (như cũ) |
| v4 | 2 ý, một `confidence < TAU_INTENT` / một intent chưa bật (tiêm `enabled_intents`) | con đó E1 `intent_low_confidence` / `intent_not_enabled`; con kia chạy |
| v5 | `span` không có trong câu | con E1 `split_span_invalid`, `redacted_request` = cả câu |
| v6 | slot của ý 2 nằm ở đoạn của ý 1 (vd `device_id` chỉ có trong span 1) | ý 2 không nhận slot đó (`sanitize_slots(text=span)`) |
| v7 | ý `account` có `target_user` sai mẫu | `ctx_flags.target_is_other=True` ở **con đó**, con kia không |
| v8 | 1 ý (đơn ý) | hành vi cũ y nguyên — toàn bộ test B3/gate cũ xanh **không sửa kỳ vọng** |
| v9 | 3 ý / 4 ý | 3 / 4 con, `index` theo thứ tự LLM |
| **c1** | Seed con (bảng 5.2.3) | đúng từng khoá; `facts == {}`; `requester_context` == của cha; không khoá lạ (`check_state_keys`) |
| c2 | `goto` con | audit `child_started` (`CLASSIFYING → DIAGNOSING`, step B5) / `child_not_runnable` (`→ ESCALATED`, E1) |
| c3 | `start` hai lần cùng `cid` | lần 2 không chạy gì (thread đã có state); 1 dòng `turns` submit |
| c4 | `recover` một ticket con chưa có thread | đóng lượt, không chạy B1 |
| **k1** | Ném lỗi sau `child_create` của con 2, trước checkpoint cha (giả lập chết) → chạy lại | đúng 2 dòng `tickets` con, mỗi con chạy **1** lần (D-18); `side_effects` `child_create` 2 dòng |
| k2 | Ném lỗi giữa lượt lồng của con 1 (sau `start`, trước `child_submit`) → chạy lại cha | con 1 không chạy lại từ đầu (thread đã có state); con 2 vẫn khởi động |
| **n1** | Con B18 `notify_user` | 1 dòng `child_notices` (`kind=result`, `needs=confirm`, `source_step=B18`, `effect_key` = khoá của `effects.once`); `notify_user` của ticket thường vẫn `noop:` (không dòng notice) |
| n2 | Con B11 / B16 / B10 / B20 | `question/answer`, `rejection/none`, `answer/confirm`, `escalation/none` |
| n3 | Chạy lại node con (cùng lượt) | không nhân đôi notice (`effect_key` UNIQUE) |
| n4 | `deadlines.set` cho con / cho cha / ticket thường | con: không dòng `wait_deadlines`; cha, ticket thường: như cũ |
| **w1** | Con dừng `confirm_wait` / `clarify_wait` / kết thúc (lượt thường, qua `start_event`) | `wake_parent` được gọi **sau khi nhả khoá con** |
| w2 | Con dừng `approval_wait` | không đánh thức |
| w3 | Lượt lồng từ cha | không `after_turn` (không tự khoá chết — test có hạn thời gian) |
| **p1** | `parent_wait`: con 1 dừng, con 2 ở `approval_wait` | `interrupt`, 0 tin; đánh thức sớm → quay lại chính node, vẫn 0 tin |
| p2 | Mọi con dừng | đúng 1 tin `digest` vòng 1; notice vừa gom có `delivered_round=1`; hạn `confirm` (chỉ xác nhận) hoặc `clarify` (có câu hỏi); `awaiting` đúng |
| p3 | Chạy lại `parent_wait` sau khi đã gửi (cùng lượt) | không gửi lại, không đánh dấu lại |
| p4 | Mọi con kết thúc trước khi cha tới `parent_wait` (TC32 nhanh) | cha đóng ngay đúng `aggregate_status`, 1 tin, không cần `wake` (D-17) |
| p5 | `aggregate_children` 6 dòng + dòng đủ 3 loại (bảng 5.2.5) | đúng `final`, `aggregate_status` |
| p6 | Cha đóng | `close_reason IS NULL`, `exit_code IS NULL`, 0 `escalations` của cha; `resolution_path` NULL; truy vấn `is_parent=false` không đếm cha (D-30) |
| **r1** | `parent_reply_wait` `reply` {ý 1 confirmed, ý 2 answer} | con 1 nhận `confirmed`, con 2 nhận `user_reply` đúng chữ đã che; 2 dòng `child_event`; 1 tin user ghép trong `conversation` cha |
| r2 | `timeout` của cha | mọi con trong `awaiting` nhận `timeout` → con ở `clarify_wait` E4 `clarify_timeout`, con ở `confirm_wait` `resolved_auto_timeout_48h` |
| r3 | Chạy lại `parent_reply_wait` sau khi đã giao cho con 1 (giả lập chết) | con 1 **không** nhận lần 2 (`peek`/lệch node → bỏ, không `late_event`); con 2 nhận |
| r4 | `note` "Chưa ổn" có chuỗi injection | con E0 `injection_in_reply` (logic `confirm_wait` cũ áp ở con) |
| **a1** | `POST /reply` hợp lệ | 202; cha resume `reply` |
| a2 | thiếu ý / ý ngoài `awaiting` / `answer` cho ý `needs=confirm` | 422 `fields` đúng `child_id`; 0 `child_event` |
| a3 | cha không ở `parent_reply_wait` / ticket thường | 409 + 1 dòng `late_event` |
| a4 | `/reply`, `/messages`, `/confirm` lên ticket con | 409 `CHILD_MESSAGE` |
| a5 | không phải chủ / id giả | 403 / 404 (khuôn TC30) |
| a6 | `answer` có bí mật | bản che vào con + `conversation`; `privacy_secret_redacted` |
| a7 | `GET` cha `children_progress` ở 5 tình trạng; ticket thường | đúng `progress`/`outcome`; `null` |
| **s1** | `scan_parents` (a): cha ở `parent_wait`, mọi con đã dừng theo DB | `wake_parent` 1 lần; cha chưa ở `parent_wait` → no-op |
| s2 | (a): con chưa có dòng `turns` | đánh thức → cha khởi động con |
| s3 | (b): cha đã đóng, con có notice `needs≠none` | con nhận `timeout` (`source="worker"`) |
| **m1** | `compose_digest`: tiêu đề từ `ACTION_LABELS` / nhãn loại / ý E1; thứ tự `index`; vòng cuối chỉ câu tổng kết | đúng mẫu 5.2.5, không chữ ngoài notice + mẫu |
| m2 | Hình dạng tin `digest` (5.2.6) | khoá đúng; `items[].kind` ∈ 4 giá trị FE |
| **h1** | ScriptedLLM resolver: ticket con không thẻ | preset `<thẻ cha>-<i>`; thiếu → `ScriptExhausted` |
| h2 | 13 preset cũ + 9 preset T24 + preset mới cùng tập khoá | xanh (`b14_*` không đổi giá trị) |
| **g\*** | `make gate5` bảng 5.2.7 | xanh |

**Test cũ được phép đổi (ghi lý do từng dòng ở MẪU B):** test ghim "≥ 2 ý → E1 `multi_intent_not_enabled`" (B3) → nay chỉ còn khi 0 ý chạy được (v3); test node giả `parent_wait`/`parent_reply_wait` (chuyển import sang `graph/nodes/fake/`); test `after_turn` (thêm điều kiện dừng ở node chờ); test ghim tập `REASON_DETAILS` (+1). Test cũ khác đỏ → DỪNG hỏi.

#### 5.2.9. Mutation (`scripts/mutation/mutate_t20b.py`, khuôn `mutate_t24.py`, md5 + `git diff --stat`)

| Mã | Phá | Test phải đỏ | Lượt |
|---|---|---|---|
| M-T20b-1 | Ý `out_of_scope` bị bỏ im lặng (không tạo con E1) | v2, tc32 | ×2 |
| M-T20b-2 | `sanitize_slots(text=cả câu)` thay vì `span` | v6 | ×2 |
| M-T20b-3 | `child_create` gọi thẳng, không `effects.once` | k1 | ×2 |
| M-T20b-4 | Con ở `approval_wait` tính là đã dừng | p1, tc34 | ×2 |
| M-T20b-5 | Notifier của con gửi thẳng (không ghi `child_notices`) | n1 | ×2 |
| M-T20b-6 | Con đặt hạn riêng | n4 | ×2 |
| M-T20b-7 | Không đánh dấu `delivered_round` | p2, p3 | ×2 |
| M-T20b-8 | `aggregate_children` đảo ưu tiên (REJECTED > ESCALATED) | p5 | ×2 |
| M-T20b-9 | Cha ghi `exit_code` | p6 | ×2 |
| M-T20b-10 | `deliver` giao lại khi đã giao (bỏ kiểm node/peek) | r3 | ×2 |
| M-T20b-11 | `/reply` bỏ kiểm `items` ≡ `awaiting` | a2 | ×2 |
| M-T20b-12 | `parent_wait` không `goto` quay lại sau `interrupt` | p1 | ×1 |
| M-T20b-13 | `after_turn` không đánh thức khi con dừng ở node chờ | w1 | ×1 |
| M-T20b-14 | Con kế thừa `ctx_flags` của ý khác | v7 | ×1 |

Lượt 1 ở DỪNG 1 (mã có đích đã code), lượt 2 + đủ 14 ở DỪNG 2.

#### 5.2.10. Soát bảo mật (security-reviewer mỗi DỪNG, chỉ diff T20b)

(1) Mỗi con có `Action` riêng qua M5 — không đường nào để kết quả rủi ro của con này áp cho con khác (seed không chép `risk`, `action`, `facts`); (2) con không bao giờ chạy B17 nhờ dữ liệu của cha: `facts={}` ở seed, B6/B11 tính lại; (3) slot của ý chỉ lấy trong `span` của chính ý (chống "mượn" đích của ý khác); (4) ý không chạy được luôn thành E1 có `escalations` — không ý nào bị bỏ im lặng; (5) con không nhắn trực tiếp: mọi `notify_user` của con ra `child_notices` (grep + test AST: không đường gửi nào khác); (6) `/reply`: chủ ticket, privacy guard trước mọi thứ ghi/giao, `extra=forbid`, `items` ≡ `awaiting` dưới khoá; (7) tin digest chỉ ghép chữ mẫu + `body` notice (đã qua mẫu/output guard ở con) + số; không chữ người dùng ngoài tin user đã che (P8); (8) không khoá chết: không chỗ nào giữ khoá con rồi chờ khoá cha (đọc `runner.py`, `late_event.py`); (9) cha không `exit_code`/`escalations`; chỉ số M9 không đổi (view `v_leaf`); (10) không đụng file cấm P14 (`git diff --stat`), `wiring.py` chỉ 1 dòng; grep import động `backend/app/risk/` rỗng.

#### 5.2.11. DỪNG

- **DỪNG 1 (15/10) — B5 + vòng cha trên graph (không cần stack):** P1–P10 (P11–P13 thuộc DỪNG 2); test-writer viết **toàn bộ** bảng 5.2.8 (ca DỪNG 2 gom `CHO_DUNG2` + `xfail(strict)`); xanh: v*, c*, k*, n*, w*, p*, r1–r4, m*. Integration bằng Runner thật + `InMemorySaver` + ScriptedLLM + bản giả store (2 thread cha/con thật, đếm tin ở `conversation` cha). Mutation lượt 1 (M-T20b-1…10). security-reviewer mục 1–5, 7–10. `make lint` + unit. Commit cục bộ. **MẪU B in danh sách file đã sửa trong `wiring.py`/`runner.py`/`late_event.py`** (để phiên git xếp rebase 6C).
- **DỪNG 2 (16/10) — API + worker + stack:** P11, P12, P13 + preset + gate5 nhiều ý (5.2.7) + a*, s*, h*, g* + gỡ hết `xfail` + mutation lượt 2 (đủ 14) + security-reviewer đủ 10 mục + `make verify G=2345` qua phiếu stack (gate5 nhiều ý chạy lần đầu — có thể phải chỉnh preset; **không** sửa kỳ vọng 5.2.7 khi chưa hỏi) + biên bản gate5 + "Spec cần sửa (T20b)" + dòng "Dồn về mốc G" (bộ 10 câu nhiều ý với LLM thật: tách đúng ≥ 9/10 — B03 §11). Commit + phiếu push. Sau verify: nạp lại KB thật qua phiên git.

#### 5.2.12. Tuấn Anh / thành viên cần biết

- **Phase 6:** T20b sửa `wiring.py` **1 dòng** (notifier, P5) — khác chỗ 6C sửa (NodeDeps/`check_strategy`/calibrator); không sửa `fakes.py`, `settings.py`, `b12`, `b17`, `audit/check.py`, `risk/*`. Ca không luật khớp ở con vẫn qua B12 như ticket thường → sau 6C ra E5 `llm_high_risk` ở con (cha chỉ tổng hợp). T20b đẩy trước 6C (P6→P5 #14).
- **Frontend:** 4 điểm hợp đồng (5.2.6) không đổi so với chốt 10/10 trừ: `items[].kind="answer"` của B10 hiển thị như `result`; `options`, `sources` chưa phát. Chặng FE "nối thật Phase 5" bỏ MSW `employee-multi` sau khi T20b gộp.
- **M9 (Dương, Duy Anh):** chỉ số vẫn trên ticket lá (`v_leaf`); thêm tỉ lệ câu nhiều ý / số tin trên lượt người dùng là việc M9 sau cổng 5 (B03 §9) — không chặn.
- **Quân:** D2 nên có ≥ 10 câu nhiều ý (B03 §11 "bộ 10 câu nhiều ý") — gồm ý lẫn ngoài phạm vi, một ý cần duyệt, một ý thiếu thông tin.
- Không thêm biến `.env`; `PARENT_RECONCILE_INTERVAL` là hằng code 60 s (B03 §7 [Đề xuất D-17]).

#### 5.2.13. Chốt khi hiện thực T20b (MẪU A, MẪU B DỪNG 1 + 2, 13–14/10) — thay chữ ở 5.2.0–5.2.12 khi lệch

| # | Chốt | Thay chỗ |
|---|---|---|
| 1 | Dòng B3 cũ là `b03_classify.py:102` (không `:98`) | 5.2.0 |
| 2 | Q-T20b-1: `wiring.py` sửa **2 dòng** (import + `notifier=ChildAwareNotifier.on_engine(engines.main, LoggingNotifier())`) | P5, P14 |
| 3 | Q-T20b-2 = B: ≥ 2 ý mà 0 ý chạy được → không ý nào trong phạm vi: `out_of_scope`; còn lại: `reason_detail` của **ý đầu tiên trong phạm vi** theo bảng 5.2.2. Code mới **không** gán `multi_intent_not_enabled` (giá trị giữ trong `REASON_DETAILS`) | P2 |
| 4 | Q-T20b-3: hạn của **cha** — đặt hạn mới thì thay mọi hạn chưa bắn của **cả hai** loại (`clarify`/`confirm`); không đụng hạn duyệt | P7 |
| 5 | TQ-2: contextvar khoá/bước của side effect đặt ở `effects.once` (không ở `run_once`) | P5 |
| 6 | P7: chạy lại `parent_wait` sau khi đã gửi vòng n → dựng lại đúng notice vòng n (không gom notice mới); `children_view`: con "kết thúc" = có `final_state` **và** không còn lượt mở | P7, 5.2.4 |
| 7 | **Q-T20b-5 — lệch D-30 có chủ đích:** cha có `exit_code` (đường lỗi, **mọi** mã) → B20 tạo escalation + tin theo mã; `db/escalations.list_open` = `is_parent = false OR tickets.exit_code IS NOT NULL` (view/chỉ số M9 không đổi). Ghi chú bàn giao của cha lỗi có mã trạng thái từng con (`awaiting_confirm[+executed]`, `awaiting_answer`, `pending_approval`, `processing`, `not_started`, `closed:<…>`; đọc lỗi → `children_status_unavailable`) — Q-T20b-9 (i) | P10, 5.2.5 |
| 8 | Q-T20b-6: `start_missing` — hết chờ pool khoá như `TicketBusy` → bỏ qua con, audit `children_not_started {busy, failed}` (ghi trước `interrupt`); `deliver` — thử lại 1 s × 5 rồi ném (E9 cha) | P4, P8 |
| 9 | FAIL-1 + NGHI-1: `deliver` so mốc `(checkpoint_id, next, values.turn_id)` của con trước/sau lượt lồng — không đổi → ném; đổi mà lượt con lỗi → không ném (lượt con mở, worker chạy tiếp) | P8 |
| 10 | `child_submit` chỉ ghi khi lượt đó thật sự khởi động con; con đã có thread mà thiếu dòng → ghi bù (Q-T20b-11) | P4 |
| 11 | P12 chạy **trong** `scan_deadlines` (không thêm job `worker.py` — test M9 ghim tập job): (a) cha được đánh thức khi `child_submit` < số con **hoặc** mọi con đã dừng theo `children_view`; (b) con mồ côi (cha đã kết thúc, notice `needs≠none` đã gửi hay chưa) chỉ nhận `timeout` **sau hạn thường** (24 h / 48 h từ `delivered_at`, chưa gửi thì `created_at`) — Q-T20b-9 (ii); tối đa 20 cha + 20 con mỗi lượt, ngân sách riêng từng bước, không huỷ lượt graph giữa chừng (Q-T20b-10) | P12 |
| 12 | P11: `start_event(wait_node=…, validate=…)` + `InvalidReply`; khoá `items` phải dạng `<cha>-<1–2 chữ số>`, 422 **không** dội lại khoá (`fields:["body.items"]`); che chữ qua `api/desk.redact_reply_items` (Q-T20b-8, test AST N1 công nhận helper) | P11, 5.2.6 |
| 13 | Q-T20b-12: `child_create.result_ref` = `<cid>\|<n>\|<type>`; B3 chạy lại khi phục hồi mà lệch số ý / loại ý / không còn tách → E9 cha (cache `b03_classify` không bảo đảm cùng kết quả) | P3 |
| 14 | **Q-T20b-13:** `audit/check._point8` (code Phase 4) — ticket **cha** (nhận qua dòng audit B5 `split_into_<n>_children`) đạt điểm log 8 bằng `detail.aggregate_status ∈ AGGREGATE_STATUSES` thay cho `close_reason\|exit_code`; lá/con vẫn đòi `close_reason\|exit_code` | P14, 5.2.10 |
| 15 | Mutation đủ 14 mã, 14/14 đỏ; gate5 nhiều ý 5 kịch bản xanh lần đầu không chỉnh preset | 5.2.9, 5.2.7 |
| **Nợ (không chặn)** | Con chưa khởi động của cha lỗi treo `final_state NULL` (ghi chú bàn giao có `not_started`); mỗi cha đang chạy cần 2 kết nối khoá (tăng pool — `settings.py` — sau cổng 5); span các ý chồng nhau; `redacted_request` của con = chuỗi `span` LLM trả; `scan_parents` chỉ bắt `TimeoutError` khi đọc con mồ côi; nguồn trích B10 của con chưa vào digest; M9 `E1_REASONS` chưa có `split_span_invalid` (vào nhóm `other`) | — |
| **Dồn về mốc G** | Bộ 10 câu nhiều ý với LLM thật: tách đúng ≥ 9/10 (B03 §11), kèm kiểm span thật nằm trong câu | — |

## 6. Chặng T23a — đóng nhánh `ml-gan`: B2 lớp 3 chế độ `shadow` (tầng A, Opus, 1 DỪNG) [Chốt 10/10] — **ĐÓNG** (`6ad51c1` + `a463150`, CI xanh)

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

### 6.5. Chốt khi hiện thực T23a — 11 mục "Spec cần sửa (T23a)" (MẪU B duyệt 10/10; không chặn commit)

| # | Chốt / nợ | Xử lý |
|---|---|---|
| 1 | P9: B2 đọc `get_settings().b2_classifier_mode` trong `make` — lệch quy ước NodeDeps | Nợ: chuyển vào NodeDeps khi có chặng đụng `fakes.py` (không phải T20a) |
| 2 | `thresholds.json` (B02 §7, P11 §4.3) là **điều kiện trước `active`** | D-44 điều kiện chuyển `active` |
| 3 | Độ trễ hàng chờ chung ml-service (classify 48 cửa sổ CPU vs timeout 2 s + retry, `to_thread` không huỷ) chưa đo | Dồn mốc G (đo cùng rerank) |
| 4 | t2: audit `ml_error` chỉ ghi ở nhánh E2 | ghi nhận — đúng hợp đồng audit B2 |
| 5 | `GUARD_MODEL_DIR` không bị ép nằm dưới `/ml_models` (Q-T23a-3) | Nợ trước `active` |
| 6 | Phạm vi P1 thêm `backend/app/ml/ports.py` (giá trị `MlError` `too_many_windows` + docstring) | 6.1 P1 đọc kèm `ports.py` |
| 7 | `.gitignore` giữ `ml_models/*-clf/` (bản dev) | ghi nhận |
| 8 | Backend `ClassifyOut.p_malicious` không chặn miền [0, 1] / NaN | Nợ trước `active` |
| 9 | SHA chỉ phủ `model.safetensors` và là tuỳ chọn | Nợ trước `active` |
| 10 | Traceback 500 của `/classify` có thể mang chuỗi nếu tokenizer ném lỗi kèm đầu vào | Nợ trước `active` (bắt lỗi, trả mã chung) |
| 11 | Đích M-T23a-6 (lật chỉ số lớp) | ghi nhận — test `test_class_index_from_id2label` bắt |

## 7. Chặng T24 — executor + hoàn tác 6 hành động mới + **bật 4 intent** + `make gate5` (tầng A, Opus, 2 DỪNG) [viết đủ 13/10 — soát code tại `03b4450`] — **ĐÓNG** (`216c89d` + `457239d`, verify G=2345 + G=5 xanh, CI xanh)

**Mục tiêu:** ticket đơn ý của 4 intent chạy **đầu-cuối trên stack** tới B17 thật: ghi đúng một lần, hoàn tác theo từng bước, tin kết quả B18 theo mẫu, ghi chú bàn giao E7 đủ 4 phần; `ENABLED_INTENTS` mặc định 4 intent; cổng 5 tự động phần đơn ý xanh bằng `make gate5`.
**Đầu vào:** thư mục chính ở `03b4450` (T20a), cây sạch, KB thật đã nạp. **Đầu ra:** 2 commit cục bộ + phiếu push. **Khi đẩy:** báo Phase 6 "6C mở được" (T24 là chặng cuối sửa `b17_execute.py` trước 6C — G6-1).
**Nghi thức:** `PLAN-T24.md` + MẪU A · 2 DỪNG · test-writer viết bảng 7.5 trước code (`CHO_DUNG2` + `xfail(strict)`) · mutation (phần A ×2) + md5 · security-reviewer mỗi DỪNG. **Model:** Opus.

### 7.0. Sự thật của code tại `03b4450`

| Chủ đề | Code hiện có | Hệ quả |
|---|---|---|
| PLAN | `executor/plans.py`: `PLAN` chỉ 3 hành động VPN; `step_args`/`undo_args` chỉ VPN; `check_plans` đòi `meta.reversible == (spec.reversible ∈ {full, partial})` **cho từng bước** | Kế hoạch nhiều bước có bước không hoàn tác được (license trả phí) sẽ bị từ chối khởi động → nới luật kiểm (P2) |
| Executor | `executor/vpn.py` `VpnExecutor`: chạy tuần tự, `begun` trước mỗi bước, gọi đúng 1 lần, lỗi → `_rollback` ngược; bước `undo=None` khi hoàn tác → ghi `"UNDO_FAILED: no_undo"`; `_handoff` viết riêng cho VPN ("chứng chỉ… VPN gateway"); `_outputs` chỉ `serial`, `expires_on` | P3, P5 |
| Registry ghi | `executor/wiring.build_write_registry` chỉ nạp `vpn_write.write_handlers`; adapter `ad_write`, `software_write`, `fileserver_write` **đã có** (đủ 12 tool ghi + hoàn tác) | P6 |
| Mock ghi | `install` không đòi license; `licenses/{name}/assign` 409 `not_a_paid_license` / `no_license_available`; `reset-password`, `unlock`, `lock` 404 khi thiếu `account_type`; `grant` 404 thư mục lạ; `extend` 404 khi chưa có dòng quyền, trả `previous_expires_at` | Bảng 7.2 |
| B18 | `messages.result_text(action_type, device_id, outputs, facts)` chỉ 3 hành động VPN; `RESULT_ACTIONS` 3 phần tử; `ticket_state.EXEC_OUTPUT_PATTERNS` chỉ `serial`, `expires_on` | P4 |
| B17 | Kiểm lại luật/duyệt/hash/người (`ad_get_user` người gửi + `requested_for` + người duyệt) — **chung cho mọi intent**, không cần sửa logic; chỉ đổi lời gọi `result_text` | P4 |
| Bật intent | `settings.enabled_intents` mặc định `["vpn"]` (`settings.py:186`); `.env.example:130` chú thích; roster 4 intent có (T20a); `check_plans` + `RESULT_ACTIONS` chặn khởi động khi thiếu | P1 |
| Stack | `tests/stack/gate3.py`, `gate4.py` (khuôn), preset `config/scripted/*.yaml` (13 file, có khoá `b14_*` của 6B) | P8, P9 |

### 7.1. P-T24 (agent không hỏi lại)

| Mã | Chốt |
|---|---|
| **P1** | **Bật 4 intent (Q-5-7):** `settings.enabled_intents` mặc định `["vpn", "account", "software", "access"]`; `.env.example` sửa chú thích. Khởi động phải qua `check_intent_config`, `check_approvers_config`, `check_plans` với 4 intent. `NodeDeps.enabled_intents` (test) **không đổi** (`{"vpn"}`) — test cũ không đổi hành vi. Máy nào `.env` đặt `ENABLED_INTENTS` tường minh → Tuấn Anh tự sửa (agent không đọc `.env`) — ghi trong MẪU B |
| **P2** | **PLAN 6 hành động + bước có điều kiện:** `Step` thêm `when: Literal["always", "paid_license"] = "always"`; `plan_for(action) -> tuple[Step, ...]` lọc theo `when` — `"paid_license"` giữ khi `action.facts.get("license_paid") is not False` (**thiếu fact → coi như có phí**: không bao giờ cài phần mềm có phí mà chưa cấp license). Bảng 7.2. `check_plans` sửa: mỗi bước là tool ghi đã khai báo; `step.undo == spec.undo_tool`; metadata `reversibility == "none"` ⇒ không bước nào có `undo`; `reversible` ⇒ **ít nhất một** bước hoàn tác được; hành động không ghi (PLAN rỗng) chỉ được là hành động chỉ đọc (`check_vpn_status`, `view_permissions`). Giữ: thiếu PLAN / thiếu mẫu B18 → không khởi động |
| **P3** | **Executor chung (đổi tên `VpnExecutor` → `PlanExecutor`, file `executor/plan_executor.py`; `executor/vpn.py` xoá, cập nhật import ở `main.py` (dòng import, ngoài khối `# M9`) và test):** giữ nguyên mọi bất biến 3h (has_begun → E7; đủ timeout TRỌN trước `begun`; `begun` commit riêng trước mỗi bước; gọi ĐÚNG 1 lần; lỗi sau `begun` → `ExecutionInterrupted`; P6 chữ lỗi tập đóng). **Hoàn tác theo từng bước:** bước `undo=None` → **không gọi**, ghi `(tool, "not_reversible")` (thay `"UNDO_FAILED: no_undo"`); mọi bước đã xong đều `not_reversible` → `rollback_status="not_attempted"`; `action.reversible=False` → `not_attempted` như cũ. `_write_calls` (B17) không đếm `not_reversible` |
| **P4** | **B18 theo mẫu (không LLM):** `result_text(action, outputs, facts, *, requester_id, rows=())` thay chữ ký cũ (VPN giữ **nguyên chữ**); mẫu 6 hành động ở bảng 7.3; `RESULT_ACTIONS` đủ 9. `EXEC_OUTPUT_PATTERNS` thêm `delivered_via` `^(email|sms)$`, `version` `^[0-9A-Za-z.+-]{1,32}$`, `level` `^(read|write|full)$`, `software` `^[a-z0-9][a-z0-9.+#-]{0,63}$`, `license_id` `^LIC-[a-z0-9.+#-]{1,64}-[0-9]{3}$` (khoá lạ / sai mẫu bị BỎ như cũ). `view_permissions`: `rows` = `state["diagnostics"]["check_current_permissions"]` (B6, dữ liệu tool) — tối đa 10 dòng, mỗi dòng chỉ `path` qua `RESOURCE_PATH`, `level` enum, ngày hết hạn; dòng sai mẫu bị bỏ; không có → câu "chưa thấy quyền nào" [Suy luận — agent kiểm B6 có lưu `diagnostics` cho access] |
| **P5** | **Ghi chú bàn giao E7 4 phần theo hành động** (`handoff_note`: "Đã làm / Lỗi ở bước (mã) / Hoàn tác / L2 cần làm tay") — phần "L2 làm tay" theo bảng 7.4; giữ câu "có thể đã được áp dụng" cho `timeout`/`http_5xx`/`other`. Chỉ ghép tên tool, mã lỗi tập đóng, định danh qua regex (`USER_ID`, `DEVICE_ID`, `RESOURCE_PATH`, tên phần mềm chuẩn hoá), ngày |
| **P6** | **Registry ghi đủ 4 hệ thống:** `build_write_registry` nạp `ad_write` + `vpn_write` + `software_write` + `fileserver_write` (token `svc_executor`, breaker riêng); test: mọi tool ghi trong `REGISTRY` có handler. Hợp đồng import-linter 3 không đổi |
| **P7** | **Tham số ghi chỉ từ `Action`** (`step_args`/`undo_args`, bảng 7.2): `user_id = action.requested_for` (không bao giờ người gửi); `extend_permission` **không** gửi mức quyền (`ExtendIn` giữ nguyên — Q-T22a-8); `reset_password`/`unlock_account` `account_type` từ `params`; `assign_paid_license(user_id=requested_for, software_name=params.software_name)` |
| **P8** | **`make gate5`** (`tests/stack/gate5.py`, khuôn gate3/gate4; `Makefile` + `scripts/verify.sh` nhận `G` có chữ số 5, vd `G=2345`): kịch bản bảng 7.6. Preset mới `config/scripted/{tc01,tc03,tc07,tc08,tc17,tc18,tc21a,tc21b,hb04}.yaml` — **mỗi file đủ mọi khoá prompt của 13 preset cũ, kể cả `b14_*`** (chép giá trị an toàn của `default.yaml`). **Không sửa 13 preset cũ.** Lỗi hệ thống giả qua `/_admin/faults` của mock (như gate3) |
| **P9** | **Nợ an toàn nhỏ từ T20a (làm luôn):** N8 — `access.same_department` chỉ đặt khi **cả hai** phòng ban khác rỗng; N7 — `approval_wait._rejected` thiếu `requester_context` → coi đích là "người khác" chỉ ở chữ (không đổi hành vi) — **chỉ ghi test ghim**, không sửa |
| **P10** | **Không** sửa: `risk/*`, `b12_assess.py`, `policy.json`, `domain/facts.py`, `tools/diagnosis/*` (trừ N8), `config/prompts/*`, 13 preset cũ, `llm/*`, M9 (`monitor/*`, khối `# M9`, `worker.py`), `.importlinter`, migration, `docker-compose.yml`, `.env*`, `pyproject.toml`/`uv.lock`, `kb/*`, `eval/scenarios/*`. Sửa được (agent chính, không giao subagent): `executor/*`, `b17_execute.py`, `domain/messages.py`, `domain/ticket_state.py` (chỉ `EXEC_OUTPUT_PATTERNS`), `settings.py` (chỉ mặc định `enabled_intents`), `Makefile`, `scripts/verify.sh`, `main.py` (chỉ dòng import executor) |

### 7.2. PLAN 6 hành động mới (P2, P7)

| `action_type` | Bước (thứ tự) | `undo` | Tham số bước (từ `Action`) | Mock: lỗi dữ liệu |
|---|---|---|---|---|
| `reset_password` | `reset_password` | `lock_account` (partial) | `user_id=rf`, `account_type` | 404 thiếu tài khoản loại đó |
| `unlock_account` | `unlock_account` | `lock_account` | như trên | như trên |
| `install_software` | ① `assign_paid_license` (`when="paid_license"`) ② `install_software` | ① **không** (reversible none) ② `uninstall_software` | ① `user_id=rf`, `software_name` ② `device_id`, `software_name` | ① 409 `no_license_available`/`not_a_paid_license`; ② 404 máy/phần mềm lạ |
| `view_permissions` | `()` — không ghi | — | — | — |
| `grant_permission` | `grant_permission` | `revoke_permission` | `user_id=rf`, `resource_path`, `level=permission_level`, `duration_days` | 404 thư mục lạ |
| `extend_permission` | `extend_permission` | `restore_permission_expiry(expires_at=previous_expires_at)` | `user_id=rf`, `resource_path`, `duration_days` (không mức quyền) | 404 chưa có dòng quyền |

**Vì sao license trước, cài sau [Đề xuất]:** giữ chỗ license trước (409 hết license → dừng, chưa ghi gì); cài lỗi sau khi đã cấp license → **không gọi hoàn tác** (license không thu hồi được qua tool) → đúng câu cổng 5 "phần mềm có phí lỗi khi cài → không gọi hoàn tác" [Chốt `huong-dan` §5.1]. Hoàn tác thật (`undone`) chỉ xảy ra ở kế hoạch nhiều bước có bước hoàn tác được đứng trước bước lỗi — 6 hành động hiện tại không có ca đó trên stack; cơ chế `undone`/`partial`/`undo_failed` được ghim ở mức executor bằng PLAN tiêm (test x6–x8).

### 7.3. Mẫu tin B18 (P4) — VPN giữ nguyên chữ

| Hành động | Mẫu (`{…}` = giá trị đã qua regex; thiếu → bỏ cụm) |
|---|---|
| `reset_password` | "Đã đặt lại mật khẩu tài khoản {loại} của {đích}. Mật khẩu tạm đã gửi qua {email}; cần đổi ở lần đăng nhập tới. Bạn đăng nhập thử rồi xác nhận giúp mình nhé." |
| `unlock_account` | "Đã mở khoá tài khoản {loại} của {đích}. Bạn đăng nhập thử rồi xác nhận giúp mình nhé." |
| `install_software` | "Đã cài {software}{ phiên bản version} lên máy {device_id}. Bạn mở thử rồi xác nhận giúp mình nhé." |
| `view_permissions` | "Quyền truy cập hiện có của {đích}: {path} ({level}, hết hạn {dd/mm/yyyy} \| không thời hạn); … Bạn xem đã đủ chưa rồi xác nhận giúp mình nhé." (≤ 10 dòng; không dòng → "chưa thấy quyền nào") |
| `grant_permission` | "Đã cấp quyền {level} thư mục {path} cho {đích}{, hiệu lực tới dd/mm/yyyy}. Bạn mở thử rồi xác nhận giúp mình nhé." |
| `extend_permission` | "Đã gia hạn quyền thư mục {path} của {đích} tới dd/mm/yyyy. Bạn mở thử rồi xác nhận giúp mình nhé." |

`{loại}`: `ad` → "đăng nhập (AD)", `email` → "email", `erp` → "ERP". `{đích}`: `messages.target_phrase` (T20a P11). Không chữ nào lấy từ câu người dùng ngoài định danh đã qua mẫu.

### 7.4. Phần "L2 cần làm tay" của ghi chú bàn giao (P5)

| Hành động | Lỗi | Câu |
|---|---|---|
| reset/unlock | 404 | "tài khoản {loại} của {rf} không tồn tại — xác minh lại với người dùng" |
| reset/unlock | khác | "kiểm tài khoản {loại} của {rf} trên AD; thực hiện {hành động} bằng tay nếu vẫn cần" |
| install ① | 409 | "hết license {software} (hoặc không phải phần mềm có phí) — xin thêm license rồi cài lại" |
| install ② | sau khi ① xong | "license {software} ĐÃ cấp cho {rf} và KHÔNG được thu hồi tự động — cài bằng tay hoặc thu hồi license" |
| install ② | 404 | "máy {device_id} hoặc phần mềm {software} không có trên hệ thống — xác minh lại" |
| grant | 404 | "thư mục {path} không tồn tại — xác minh lại đường dẫn" |
| extend | 404 | "{rf} chưa có quyền trên {path} — không gia hạn được, cân nhắc cấp mới (cần duyệt)" |
| mọi hành động | `timeout`/`http_5xx`/`other` | tiền tố "lệnh ở bước {tool} có thể đã được áp dụng — kiểm trên hệ thống đích trước khi làm lại" (giữ 3h) |

### 7.5. Test (test-writer viết TRƯỚC code)

| # | Ca | Kỳ vọng |
|---|---|---|
| **p1** | `check_plans` với 4 intent bật, PLAN thật | xanh |
| p2 | PLAN thiếu `grant_permission` / bước `undo` sai / hành động `reversibility none` có bước `undo` / hành động `reversible` mà không bước nào hoàn tác được / PLAN rỗng cho hành động ghi | `RuntimeError` (không khởi động) |
| p3 | `plan_for` install `license_paid=False` / `True` / **thiếu** | (install) / (assign, install) / (assign, install) |
| p4 | `step_args` 6 hành động (bảng 7.2) — `user_id` luôn `requested_for` (account `target_user=nv005`, người gửi nv001 → `nv005`); extend không có khoá mức quyền | đúng |
| p5 | `undo_args`: `lock_account(user_id, account_type, reason="admin")`, `uninstall_software(device_id, software_name)`, `revoke_permission(user_id, resource_path)`, `restore_permission_expiry(…, expires_at=previous_expires_at)` | đúng |
| **x1** | Executor install có phí: assign OK, install 500 | 2 lời gọi ghi, 0 hoàn tác; `rollback_status="not_attempted"`; details `[("assign_paid_license","not_reversible")]`; handoff có câu license 7.4 + "có thể đã được áp dụng" |
| x2 | install có phí: assign 409 | 1 lời gọi; `none_needed`; handoff "hết license" |
| x3 | install free: install 500 | 1 lời gọi; `none_needed`; "có thể đã được áp dụng" |
| x4 | reset OK / grant OK / extend OK | `success`, `outputs` đúng khoá + mẫu (P4) |
| x5 | `view_permissions` | 0 lời gọi ghi, 0 `begun`, `success` |
| x6 | PLAN tiêm 2 bước hoàn tác được, bước 2 lỗi 409 | bước 1 `undone`, `rollback_status="undone"`, 3 lời gọi |
| x7 | như x6, hoàn tác lỗi | `undo_failed` + `transaction_log.undo_failed` |
| x8 | PLAN tiêm 3 bước (hoàn tác được, không hoàn tác được, lỗi) | `partial`: bước 1 `undone`, bước 2 `not_reversible` |
| x9 | mọi bất biến 3h giữ (has_begun → E7; thiếu timeout trước begun → E2; lỗi sau begun → `ExecutionInterrupted`) | test VPN cũ của executor xanh, chỉ đổi tên lớp/import |
| x10 | `_write_calls` | không đếm `not_reversible` |
| **m1** | `result_text` 6 mẫu bảng 7.3 + 3 mẫu VPN (chữ cũ y nguyên) | đúng |
| m2 | outputs sai mẫu (`version="1.0; rm -rf"`, `level="admin"`, path có `..`) | bị bỏ, không vào tin |
| m3 | `view_permissions` rows: 12 dòng → 10; dòng path sai mẫu bị bỏ; không dòng | đúng |
| m4 | handoff 4 phần mỗi hành động × lỗi bảng 7.4 | chứa đủ "Đã làm", "Lỗi ở bước", "Hoàn tác", "L2 cần làm tay" |
| **w1** | `build_write_registry`: mọi tool ghi trong `REGISTRY` có handler | xanh |
| w2 | `settings.enabled_intents` mặc định 4 intent; `open_runtime` thật (DB test) khởi động với 4 intent | xanh |
| w3 | `NodeDeps.enabled_intents` mặc định vẫn `{"vpn"}` | xanh |
| **n8** | `same_department` khi một phòng ban rỗng | không đặt |
| **g\*** | `make gate5` — bảng 7.6 | xanh |

**Test cũ được đổi:** `test_executor_vpn.py` (tên lớp/import, đổi tên file theo lớp mới nếu cần; `"UNDO_FAILED: no_undo"` → `"not_reversible"` nếu có ca); `test_executor_plans.py` (luật `check_plans` mới — giữ mọi ca từ chối cũ còn đúng ý); `test_messages*`/`test_b17*` chỉ chữ ký `result_text`; test ghim mặc định `enabled_intents` nếu có. Test cũ khác đỏ → DỪNG hỏi.

### 7.6. `make gate5` — cổng 5 tự động phần đơn ý (P8)

> **Ghi chú 09/11/2026 — bản demo `lo-0811` (Q5):** ví dụ **tc17** đổi "cài utorrent" → **"cài photoshop"** (utorrent nay bị R21 deny);
> kỳ vọng giữ nguyên (catalog 404 = dữ liệu → R13 → chờ duyệt, 0 ghi). Dòng tc17 dưới đây là của bản đo, không viết lại.

| Mã | Người gửi · câu (preset) | Kỳ vọng |
|---|---|---|
| tc01 | nv001 "đặt lại mật khẩu tài khoản AD" | R01 AUTO → `POST /ad/users/nv001/reset-password` đúng 1 lần → tin result → xác nhận → `S_RESOLVED` |
| tc03 | nv001 "cài Zoom" (máy suy LAP-0342) | R11 AUTO → 1 lời gọi install, 0 assign → `S_RESOLVED` |
| tc07 | nv001 "đặt lại mật khẩu AD cho svc_backup" | `approval_required` R03 (all R03, R04) → phiếu l1_01 → duyệt → B17 kiểm lại người gửi + `svc_backup` → reset `svc_backup` 1 lần |
| tc08 | nv002 "xin quyền đọc finance/Q3 30 ngày" | `approval_required` R07 (all R07, R09) → l1_01 **từ chối** có lý do → `S_REJECTED`, tin "Yêu cầu cấp quyền truy cập cho thư mục finance/Q3 chưa được duyệt. Lý do: …", **0 lời gọi ghi** |
| tc17 | nv001 "cài utorrent" | catalog 404 = dữ liệu (không E2) → `in_catalog=False` → R13 → chờ duyệt (`S_PENDING_APPROVAL`), 0 ghi |
| tc18 | nv001 "đặt lại mật khẩu AD", fault 500 trên tiền tố `/ad/users/nv001/privilege` (`check_privilege_level`; **không** đặt lỗi trên `/ad/users/nv001` — B1 dùng chung, sẽ ra E2 ở B1 thay vì B7) | B7 → E2 `tool_system_error`, tin mẫu E2, 0 ghi |
| tc21a | nv001 "cài Zoom", fault install 500 | E7 `exec_failed`, 1 lời gọi ghi, ghi chú bàn giao 4 phần có "có thể đã được áp dụng" |
| tc21b | nv001 "cài Adobe Acrobat Pro" → R14 → duyệt → assign OK, fault install 500 | E7, **0 lời gọi hoàn tác** (không `uninstall`, không thu hồi license), handoff câu license 7.4 — *cổng 5 "phần mềm có phí lỗi khi cài → không gọi hoàn tác"* |
| hb04 | nv001 "cài AutoCAD" → R14 → duyệt → assign 409 `no_license_available` | E7, 1 lời gọi ghi, handoff "hết license" (đúng dữ liệu D1 HB04 — báo Quân sửa `expected_exit`) |

Mỗi kịch bản: đếm lời gọi ghi qua `/_admin/calls` của mock; audit đủ điểm log áp dụng (1, 2, 4, 7, 8 — và 5/6 khi duyệt); không câu người dùng trong audit. Kết quả mỗi lượt ghi `tests/stack/bienban-gate5-<ngày>.md` theo khuôn gate4. **TC12** (nhiều ý) thuộc T20b; TC13, TC15, TC16, TC28 đã xanh ở gate2/gate3 (không lặp).

### 7.7. Mutation (`scripts/mutation/mutate_t24.py`, khuôn `mutate_t20a.py`)

| Mã | Phá | Test phải đỏ | Lượt |
|---|---|---|---|
| M-T24-1 | Hoàn tác gọi cả bước không hoàn tác được | x1, x8 | ×2 |
| M-T24-2 | `plan_for` bỏ bước license | p3, x1, x2 | ×2 |
| M-T24-3 | thiếu `license_paid` → coi như miễn phí | p3 | ×2 |
| M-T24-4 | `step_args` dùng người gửi thay `requested_for` | p4 | ×2 |
| M-T24-5 | extend gửi mức quyền | p4 | ×2 |
| M-T24-6 | `result_text` chép giá trị không qua regex | m2 | ×2 |
| M-T24-7 | handoff bỏ phần "L2 cần làm tay" | m4 | ×2 |
| M-T24-8 | `check_plans` bỏ luật "reversibility none ⇒ không undo" | p2 | ×2 |
| M-T24-9 | `_write_calls` đếm `not_reversible` | x10 | ×2 |
| M-T24-10 | mặc định `enabled_intents` về `["vpn"]` | w2 | ×1 |
| M-T24-11 | registry ghi thiếu `fileserver_write` | w1 | ×1 |
| M-T24-12 | `same_department` với chuỗi rỗng → True | n8 | ×1 |

### 7.8. Soát bảo mật (security-reviewer)

(1) B17 vẫn là điểm ghi duy nhất (import-linter 3 + test); (2) mỗi bước ghi gọi đúng 1 lần, không retry; (3) tham số ghi chỉ từ `Action`, `user_id` = `requested_for`; (4) không bao giờ gọi hoàn tác cho bước không hoàn tác được; (5) thiếu `license_paid` → có bước license (không cài phần mềm có phí khi chưa cấp license); (6) tin B18 + ghi chú bàn giao + `transaction_log.detail` không chép chữ hệ thống ngoài/người dùng ngoài định danh qua mẫu (luật 8.9); (7) mật khẩu tạm không bao giờ vào phản hồi/tin/audit (mock không trả — test ghim `ResetPasswordResult` không có trường mật khẩu); (8) bật 4 intent không làm khởi động với cấu hình thiếu (fail-closed còn nguyên); (9) không đụng file cấm P10; grep import động `backend/app/risk/` rỗng.

### 7.9. DỪNG

- **DỪNG 1 — executor + B18 (không cần stack):** P2–P7, P9 (N8) + test p*, x*, m*, w1, n8 + mutation lượt 1 (M-T24-1…9) + security-reviewer (1–7, 9) + `make lint` + unit. Commit cục bộ.
- **DỪNG 2 — bật intent + gate5:** P1, P8 + w2, w3, g* + gỡ xfail + mutation lượt 2 (đủ 12) + security-reviewer đủ 9 + `make verify G=2345` qua phiếu stack (gate5 lần đầu chạy trên stack — có thể phải chỉnh preset; **không** sửa kỳ vọng bảng 7.6 khi chưa hỏi) + biên bản gate5 + "Spec cần sửa (T24)" + dòng "Dồn về mốc G" (TC07/TC08 với LLM thật). Commit + phiếu push + **báo Phase 6 "6C mở được"**. Sau verify: nạp lại KB thật qua phiên git.

### 7.10. Tuấn Anh / thành viên cần biết

- **`.env`:** nếu máy nào đặt `ENABLED_INTENTS` tường minh thì xoá dòng đó (mặc định mới đã đủ 4) — Tuấn Anh báo thành viên sau push.
- **Quân:** HB04 (AutoCAD hết license) — kỳ vọng thật là E7 (`assign_paid_license` 409), không phải `expected_exit: null`.
- **Phase 6:** preset mới (9 file) có khoá `b14_*` giá trị an toàn của `default.yaml` — 6C sửa `b14_*` thì sửa cả 9 file; T24 sửa `b17_execute.py` (chữ ký `result_text`) → 6C rebase sau T24.
- **M9:** sau push, phân bố intent đổi (4 intent bật) — báo Dương/Duy Anh.

### 7.11. Chốt khi hiện thực T24 (PLAN-T24 duyệt, MẪU B DỪNG 1 + 2, verify — 13/10; viết bù 14/10) — thay chữ ở 7.0–7.10 khi lệch

| # | Chốt | Thay chỗ |
|---|---|---|
| 1 | Q-T24-1: `scripts/verify.sh` nạp **KB thật** `kb/` (bước 11) ngay trước gate5 (bước 12) → sau lượt có chữ số 5 stack kết thúc ở KB thật; **bỏ** bước "nạp lại KB thật sau verify" (lượt không có 5 vẫn để stack ở KB fixture) | 7.9, P8 |
| 2 | Q-T24-2: `{đích}` của bảng 7.3 dùng `messages.person_phrase` (không `target_phrase`) | 7.3 |
| 3 | Q-T24-5: `view_permissions` không có dữ liệu chẩn đoán → "chưa đọc được danh sách quyền"; rỗng thật → câu "chưa thấy quyền nào" | P4, 7.3 |
| 4 | Q-T24-6: `same_department` chỉ **bỏ** khi **cả hai** phòng ban rỗng; một phía rỗng → `False` (R09 vẫn khớp) | P9 (thay "chỉ đặt khi cả hai khác rỗng"), 7.5 n8 |
| 5 | Q-T24-7: `EXEC_OUTPUT_PATTERNS["version"]` = `[0-9]+(\.[0-9]+){0,3}`; `{software}` của tin B18 lấy từ `action.params.software_name` (đã chuẩn hoá), không từ tên tool trả về | P4 |
| 6 | S1: `executor/vpn.py` → `executor/plan_executor.py`, `VpnExecutor` → `PlanExecutor`; `graph/fakes.py:127` (file cấm T24) còn chữ `executor/vpn.py` — sửa khi có chặng được đụng `fakes.py` | P3 |
| 7 | Q-T24-8: `test_b4_open_runtime_accepts_repo_approvers_copy` truyền `enabled_intents=["vpn"]` + ca ghim ngược `test_t24_default_four_intents_vpn_only_roster_refuses` (4 intent mặc định + roster chỉ vpn → không khởi động) | 7.5 (test cũ được đổi) |
| 8 | **Q-T24-10:** luật bí mật `password` (`config/privacy_patterns.json`: "mật khẩu" + ≤ 4 từ + `:`/`=`) che phần sau dấu `:` của thẻ `[fake:tcNN]` → mất thẻ → preset `default`. Câu kịch bản stack có "mật khẩu" phải có dấu câu cắt trước thẻ (gate5 TC01/TC07/TC18 thêm dấu chấm cuối câu; kỳ vọng 7.6 không đổi); `test_q_t24_10_tag_survives_real_privacy_guard` ghim | 7.6, README stack |
| 9 | Q-T24-11: `.gitignore` chặn `backend/tests/stack/bienban-gate5-2*.md` (như gate4) — biên bản gate không commit | 7.6 |
| 10 | Preset mới 9 file đủ 8 khoá như `default.yaml` (`b14_*` an toàn); 13 preset cũ không đổi | P8 |
| 11 | Mutation lượt 1 9/9 + lượt 2 **12/12** ĐỎ; verify G=2345 lượt 2 (gate2 89/0, gate3 66/0, gate4 73/0) + G=5 lượt 3 gate5 **115/0** (lượt 1 hỏng do máy ngủ — không tính; lượt 2 gate5 đỏ do #8) | 7.7, 7.6 |
| **Nợ (không chặn)** | **NGHI-5 / Q-T24-9:** `docker-compose.yml` không truyền `ENABLED_INTENTS` (không `env_file`) → trên stack `.env` **không** thu hẹp được intent; khi thêm vào `x-backend-env` phải xử lý chuỗi rỗng = dùng mặc định (`enabled_intents` list `min_length=1`) + test riêng — chưa làm (T20b cấm compose); làm trước Phase 10 (ablation có thể cần tắt intent). **NGHI-1:** B18 `view_permissions` đọc dòng quyền từ `diagnostics` của B6 — đúng khi `requested_for`/path không đổi sau B6 | — |
| **Dồn về mốc G** | TC07/TC08 với LLM thật (7.9) | — |

**Mở rộng 1 → 4 loại tốn gì (S4 — số liệu trả lời GVHD, viết 17/10)** [Đã kiểm trên git]. Tính trên 6 commit T22a `6ab716e` + `5587c78`, T20a `52c8349` + `03b4450`, T24 `216c89d` + `457239d` (09–13/10); "trước" = `6ab716e^` (chỉ VPN). Không tính T20b (nhiều ý) và T23a (B2): hai việc này không gắn với số loại.

| Hạng mục | Trước | Sau | Ghi chú |
|---|---|---|---|
| Luật | 5 | 20 | `config/policy.json` +79/−1 |
| Dữ kiện (fact) | 7 | 20 | `domain/facts.py`; fact chỉ do code đọc từ tool |
| Hành động khai báo | 3 | 9 | Mỗi hành động mới cần metadata + `procedure_doc` + PLAN thực thi + hoàn tác |
| Tool | 26 | 26 | Không thêm: tool đọc/ghi/hoàn tác của cả 4 hệ thống đã đăng ký từ Phase 1c |
| Node graph / bảng DB | 16 node | 0 node mới, 0 migration | Sửa trong node có sẵn: B3, B6, B11, B17, `approval_wait`, `clarify_wait` |
| File cấu hình | — | 6 file sửa (+190/−20) | `policy.json`, `slots.yaml`, `action_metadata.yaml`, `approvers.yaml`, prompt `b03_classify`, `b11_extract_slots`; thêm 9 preset LLM giả cho `make gate5` (+144) |
| Code `backend/app` | — | 29 file (+921/−156) | 25 file sửa, 3 module chẩn đoán mới (account, software, access), `executor/vpn.py` → `plan_executor.py`. Phần **không** làm bằng cấu hình được: nguồn `action.params` cho engine luật, `build_ctx` theo đích, hợp đồng `Action` theo `action_type`, PLAN + hoàn tác 6 hành động, tin từ chối và tin B18 theo đích |
| Mock | — | 8 file (+136/−9) | Seed thêm dữ liệu tài khoản, phần mềm, quyền |
| Test | — | 21 file cũ sửa (+513/−115), 28 file mới (+5.837) | Test cũ đổi vì ghim "chỉ có VPN" hoặc tên `VpnExecutor` (mục 4.7b), không vì hành vi VPN đổi |
| Kịch bản VPN đổi kết quả | — | **0** | `backend/tests/stack/gate3.py` không sửa dòng nào; gate3 xanh ở các lượt verify của T20a (G=234) và T24 (G=2345) |
| Script | — | `rule_coverage.py` mới, `verify.sh` thêm gate5, 3 script mutation | |
| Lịch | — | 3 chặng, 6 DỪNG, 09–13/10 | |

Kết luận cho báo cáo: thêm một loại yêu cầu là mức 4 ở B12 §13 — **không chỉ sửa cấu hình** (phải viết module chẩn đoán, PLAN + hoàn tác, hợp đồng `Action`, mở rộng engine luật). Nhưng khung không đổi (graph, tool registry, DB, M5, HITL), và kịch bản cũ không đổi kết quả.

### 7.12. Sau cổng 5 — V16, V17, LLM-G (16–18/10/2026)

| # | Chốt | Thay chỗ |
|---|---|---|
| 1 | **V16** `68c7f7d` (+ `4c798a9` PROGRESS, CI 38907115329 xanh): `validate_access` ghi một dòng lý do cho mỗi 401 (mã cố định, `revoke`, `cached`; lệch giờ kèm số giây; không token/claim — P6 mục 7); `verify.sh` cổng đỏ lưu log backend/worker ra `.verify/run-*-step<N>-logs.txt` **trước** bước 8 (gồm bước 12 — gate5); bước 9 hỏi CI của đúng HEAD. Mutation 5/5; security-reviewer PASS ×2; `make verify G=2345` trên `68c7f7d` xanh (test backend 6634, gate2 91/0, gate3 78/0, gate4 73/0, gate5 227/0) | 7.9, phase4 4.4, P6 mục 7 |
| 2 | **V17** (P6→P5 #21; Tuấn Anh chốt 16/10): `description` của R17/R18/R19 trong `config/policy.json` thêm hệ quả, cùng khuôn R03–R15 — R17 "Thiết bị chưa đăng ký cần người duyệt", R18 "Yêu cầu gửi ngoài giờ hành chính cần người duyệt", R19 "Nhân viên chưa qua thử việc cần người duyệt". Chuỗi này là lý do hiện trên màn duyệt (`policy_engine` → `RiskDecision.reason`); chỉ đổi chuỗi, không đổi điều kiện/loại luật; `policy_sha256` đổi (`d6812193…` → `936f4c1c…`). **Hiện thực V17 `45f5cd7`** (+ PROGRESS): 3 dòng `description`; 2 test chép nguyên văn; mốc `scripts/mutation/mutate_4b.py` (M-4b-6/7); test ghim mọi luật `approval_required` có mô tả kết thúc "cần người duyệt" (mutation 1/1). `make verify G=345` trên `45f5cd7` xanh (test backend 6635, gate3 78/0, gate4 73/0, gate5 227/0) | `policy.json`. Giữ chữ cũ (tóm tắt/lịch sử, không phải nguồn lý do): mock frontend, `decisions.md` §1.1, spec phase3 11.2 |
| 3 | **LLM-G (mốc G, 17–18/10)** `0e74095` + `90deec7` (CI 39027370481 xanh) + DỪNG 3 `3cf0d18`: gắn LLM thật DeepSeek — chi tiết ở P2 "Chốt khi hiện thực mốc G". **Lượt 1 (17/10):** TC07/TC08 thử tay 2 lần với LLM thật — slot và luật khớp, tới chờ duyệt. 9 câu thử tay (đủ 4 loại + 2 câu nhiều ý): 8/9 đạt; câu lệch do `b03_classify` gắn `action_hint` khi câu không nêu hành động. Ca an toàn đúng cả: TC07, TC08, tc21a, câu tấn công → E0, ca không khớp luật không ra AUTO. `make vpn-smoke` 31 PASS / 9 FAIL (lỗi ở `b10_answer`, `b10_need_type`). **DỪNG 3 (17/10 22:20–23:54, `3cf0d18`):** sửa 3 prompt — `b03_classify@4` (chỉ `action_hint` của vpn), `b10_need_type@2`, `b10_answer@2` (giữ nguyên tên/lệnh trong tài liệu); `b14_*` không đổi. `make vpn-smoke` **53/0** ở cả cấu hình A (flash/flash) và B (flash/v4-pro) → NỢ-3-2 đóng; probe JSON 287/287 lời gọi hợp lệ, 0 lần sửa. **Model chốt D-51:** fast = strong = `deepseek-flash`; strong tạm tới 12:00 21/10 (chốt cùng `p_method`, Phase 6). Thêm đích `make probe F=<file.jsonl>` + script `backend/tests/probe/cong5.py`, `cong5_score.py` (mục 7.13). **Chưa** chạy `make gate5` với LLM thật; trả stack về scripted, gate5 `S=preflight` 6/0 | 7.11 dòng "Dồn về mốc G"; PROGRESS "Dồn về mốc G"; `decisions.md` D-51 |
| **Việc treo (mở)** | gate4 g4-10 HTTP 401 chập chờn (1 lần, 16/10 00:43, `1db4bd8`) — chưa tái hiện; lần đỏ sau đọc dòng `validate_access 401 reason=…` trong `run-*-step10-logs.txt` | — |
| **Việc treo (mở, 17/10)** | Tải song song: gửi 4 ticket cùng lúc → 30/40 ticket ra E2 `rag_system_error` ở B8 (ml-service quá tải: embed rỗng sau 2 lần thử lại / quá hạn rerank); 1 luồng → 0 ca E2. Lượt đo có kết quả phụ thuộc từ B8 trở đi (harness, probe p Phase 6, demo) chạy **tuần tự** cho tới khi xử lý. Cổng 5 thủ công không thuộc diện này: điểm chấm từ dòng audit B2–B5 (`cong5_score.predict`), ghi trước B8 | PROGRESS (commit 2 DỪNG 3); tin P5→P6 #21 |

### 7.13. Phần thủ công cổng 5 — ĐẠT 18/10/2026 (mở 17/10)

Cổng 5 tự động ĐẠT 15/10. Phần thủ công dồn về mốc G (`huong-dan` §5.1); **ĐẠT 18/10** — lượt Đ6 của LLM-G DỪNG 3 (01:10–01:21 18/10, `3cf0d18` + 1 dòng trần tạm, cấu hình A D-51, 4 luồng, một lần, `run_valid = hop_le`). Biên bản: `claude/bien-ban-cong-5-thu-cong.md` (chỉ Tuấn Anh đọc tới 25/10).

| # | Mục | Tiêu chí | Hiện trạng | Ai / khi |
|---|---|---|---|---|
| 1 | Intent | Macro-F1 ≥ 0,85 / 45 câu, 5 lớp; kèm F1 từng lớp, ma trận nhầm lẫn | **ĐẠT: macro-F1 5 lớp 0,9399** (4 lớp 0,9749); sai 2/45 (access → out_of_scope ra E1; out_of_scope → account). Script `backend/tests/probe/cong5.py` (chạy qua stack) + `cong5_score.py` (chấm, có test `test_cong5_score.py`), đích `make probe F=<file.jsonl>` — `3cf0d18`. Ca E2 ở B8 không đổi điểm (điểm đọc từ B2–B5) | Bộ câu v1 (100 câu: 45 phân loại + 10 nhiều ý + 15 tấn công + 30 thường; sha256 `22f7ba2d…`) Claude chat soạn 17/10 trước khi sửa prompt; script + lượt đo ở phiên LLM-G DỪNG 3 tối 17/10, sau khi chốt model **[Tuấn Anh chốt 17/10: đóng Phase 5 trong ngày, không giao thành viên — thay phân công 15/10]** |
| 2 | Chặn tấn công | ≥ 13/15; chặn nhầm ≤ 1/30; tin trung tính (so với `user_message` E0) | **ĐẠT: chặn 14/15** (L2 8, L4 6); **chặn nhầm 0/30**; tin E0 khớp `user_message` E0 14/14. L3 chưa bật (T23a: `shadow`, không nạp model). Câu không chặn (1) lọt L2 + L4, kết thúc E2 ở B8 do ml-service quá tải → chưa có bằng chứng tầng sau xử lý đúng; việc treo: chạy riêng 1 luồng, chỉ quan sát | Cùng lượt #1 |
| 3 | Recall@5 | ≥ 0,8 / 30 câu | Đã có số: Recall@5 1,000, MRR 0,848 trên 34 câu có đáp án; trả lời bừa 0 trên 22 câu âm tính (bước ingest KB thật `3362c39b` của `make verify G=35` 17/10 15:32, `.verify/run-20261017-153234.log`); thiếu biên bản. Không cần LLM | **ĐẠT** — `claude/bien-ban-cong-5-thu-cong.md` |
| 4 | Ghi chú bàn giao E7 | Đủ 4 phần: bước đã làm, đã hoàn tác tới đâu, phần L2 làm tay | **Đủ 4 phần cả 3** (toàn văn Đ5 in từ DB, đối chiếu trong biên bản); câu riêng đúng từng ca (5xx → "có thể đã được áp dụng"; license đã cấp không thu hồi; 409 hết license). Ghi chú sinh bằng mẫu, không cần LLM | gate5 17/10: 3/3 đủ nhãn; chờ Tuấn Anh ký người đọc |
| 5 | 10 câu nhiều ý (giảm rủi ro, không phải tiêu chí cổng) | Tách đúng ≥ 9/10 | **10/10** (bộ v1) | Ghi nhận |

**Quy tắc lượt đo:**
- Bộ câu chỉ để đo, không dùng chỉnh ngưỡng hay prompt **[Chốt 15/10]**.
- Lượt đo đi qua stack nên chạy tới M5 → người gán nhãn (D-43) không chạy, không đọc log lượt này. Tuấn Anh chạy (máy có key).
- Kết quả về sau 18:00 21/10 chỉ ghi số, không sửa prompt cho bản ứng viên **[Đề xuất — rà soát 16/10 §5.1 #5]**.
- Đổi `json_mode`/`extra_body` giữa hai lượt đo thì xoá `llm_cache` trước (Việc treo 36).

### 7.14. Sau cổng 5 — bật 2 model phân loại, chống dò và spam, B3-VA (18–21/10/2026) [Chốt 18/10 — D-52…D-55]

**Nguồn chi tiết:** mục này chỉ tóm tắt, khi lệch thì hai file nguồn sau thắng:
- `claude/dac-ta-bat-2-model.md` v0.6 (đặc tả các gói);
- `claude/prompt-b3-va.md` (B3-VA).

Khi lệch với `B02`, `B03-B05`, `B20`, `P2`, `P4`, `P6`, `P7`, `P9`, `P10`, `P11` thì mục này thắng. Các file đó sửa sau 21/10 theo bảng "Spec cần sửa" cuối mục.

**Mục tiêu:** đưa 2 model phân loại của nhóm vào luồng thật mà **không tăng bỏ sót**.
- **B2 `review`:** model chỉ nghi rồi chuyển người, không tự chặn, không tự cho qua; LLM chấm vẫn xem mọi câu không khớp regex.
- **B3 ghi điểm:** LLM vẫn quyết.
- **Đi kèm:** các lớp chống dò và spam phát sinh từ `review`, và bước "dính nhau" cho câu nhiều ý có ý không chắc.

| Gói | Nội dung | Quyết định | Nơi chạy | Đường lui |
|---|---|---|---|---|
| **1** (2 DỪNG) | DỪNG 1: hàm thuần cho bảng quyết định 10 dòng và bước thay nhãn che (bộ từ của Dương); 6 script đo `b2_judge_compare.py`, `b2_tau_select.py`, `_pii_fake.py`, `b2_review_offline.py`, `b3_offline.py` (có chế độ nhãn che), `cong5_score.py`. DỪNG 2: nối vào B2 — E1 `injection_suspected` (tin người dùng = tin E0, không `security_event`, ghi chú L2 có câu cảnh báo, ưu tiên "Thường"); τ qua `B2_TAU_REVIEW` (thiếu thì `review` từ chối khởi động); ghi `ml_error`, `llm_is_attack`, `llm_category` ở mọi nhánh; nợ bảo mật §6.5 #5, #8, #9 (manifest + SHA bắt buộc), #10; hàng chờ classify riêng `ML_CLASSIFY_CONCURRENCY`; `active` chỉ ở dev/test | D-52 | thư mục chính | gói đỏ hoặc không τ nào đạt → `shadow` |
| **2** | B3 ghi điểm: chuyển `seed_42.pt` → safetensors fp32 sau khi kiểm SHA đầy đủ; `check_intent`; dựng `B3Model`, tính điểm trộn của gói; `/classify_intent` trả 200; B3 ghi `model_probs`. Bước thay nhãn che chỉ bật khi đạt tiêu chí của D-53 | D-53 | thư mục chính, sau gói 1 | trượt bộ nhớ → `INTENT_MODEL_DIR` để rỗng, dùng số offline |
| **B3-VA** | Bước "dính nhau" (chồng đoạn, cụm phủ định) ở `_split`/`_splits`; `escalation_note` cho con không chắc | D-55 | thư mục chính, sau gói 2 (cùng `b03_classify.py`), sau khi DỪNG 3 push | chưa xanh → giữ D-49 |
| **2b** | 429 + `rate_limited` + migration `0010` (CHECK, index, bảng `rate_hits` đếm tin nhắn gồm `/confirm`, `v_leaf` thêm `requester_id`), ngưỡng nới bằng biến ở `verify.sh`, gate, đo, test; 2 luật M9 `requester_probe`, `requester_probe_critical`; trang Cảnh báo cho L2 (BE + phiên FE, kiểu sinh từ file OpenAPI của 2b); dòng lịch sử người gửi trong ghi chú L2 (sau khi gói 1 commit) | D-54 | worktree riêng: không stack, không `make up`; test Postgres chạy ngay trong worktree (testcontainers) | mỗi phần là một commit riêng, gộp hay bỏ độc lập |
| **3** | Vai trò `judge` cho LLM chấm: `fallback_on` chỉ với lỗi tạm thời; OpenRouter ghim nhà cung cấp, `zdr`. Chỉ làm khi Gemini hoặc Qwen qua phép thử | D-56 (nếu đổi) | thư mục chính, chiều 20/10 | không đạt → giữ DeepSeek |

**Đo** (chốt trước khi chạy, ghi trong D-52 và D-53):
- **Cổng 5 phần B2:** tính offline từ lượt 17/10, không chạy lại bộ câu.
  - Tiêu chí chính: E0 ≥ 13/15 câu tấn công và ≤ 1/30 câu thường.
  - Tiêu chí phụ: E0 ∪ E1 ≥ 13/15 câu tấn công và ≤ 3/30 câu thường.
  - Báo kèm cận Clopper-Pearson.
- **Validation 900 + 900 câu của Dương (19/10):** dùng để chọn τ và làm phép thử LLM chấm DeepSeek so với Gemini.
  - Đổi khi đạt đủ: bắt tấn công ≥ DeepSeek; E0 trên câu thường ≤ DeepSeek + 1 điểm; JSON hợp lệ ≥ 99%; p95 ≤ 3 s.
  - Gemini trượt → chạy Qwen nếu kịp trước 12:00 20/10.
- **B3 offline + phép đo nhãn che;** bộ nhớ tổng ≤ 7 GB (tính `anon`), không OOMKilled; p95 của classify và của rerank khi có tải và câu dài.
- **Ghi trước vào D-52** (03:05: tham số chọn τ; 03:25: Tuấn Anh chốt 3 luật): dòng #3 với lượt 17/10 đo bổ sung bằng 1 lần gọi lại DeepSeek cho câu đã qua để lấy `category`; tiêu chí phụ cổng 5 chỉ để báo; đổi LLM chấm chỉ khi tốt hơn có bằng chứng (cận dưới 97,5% của Δrecall > 0 và recall E0 ∪ E1 với τ chọn lại ≥ DeepSeek).
- **RQ1 chạy với `review` bật:**
  - chỉ số M5 tính trên phần giao;
  - manifest ghi `clf_mode`, model LLM chấm, τ, SHA 2 model, ngưỡng 429 đã nới cho harness;
  - đếm thêm số cảnh báo `requester_probe` và số câu kích hoạt `entangled`.

**Lịch** (hướng đã chốt: cố không cắt việc nào):

| Khi | Thư mục chính (có stack) | Worktree 2b | Tuấn Anh / người khác |
|---|---|---|---|
| CN 18/10 | Trước khi mở phiên: Claude chép tài liệu đã sửa vào `docs/spec`, phiên git commit + push. Rồi gói 1 DỪNG 1 (script đo + hàm thuần), tối gói 1 DỪNG 2 | Chống spam, gồm bảng `rate_hits` (tạo từ commit tài liệu) | 4 điểm chờ đã chốt lúc 03:25 (đặc tả mục 1, dòng 23–26); sao lưu DB lượt 17/10; khoá OpenRouter + hạn mức; gửi tin Dương (dữ liệu kèm ID nhóm + sha256), Duy Anh (SHA, fixture — hạn 22:00); DỪNG 3 đã push 01:31 (`33b7484`); phiên git khoá thư mục chính, tạo worktree 2b, dành migration `0010` |
| T2 19/10 | Gói 1 DỪNG 2 xong trước trưa; gói 2 → B3-VA (09:00 chưa có SHA thì B3-VA trước) | Luật M9 (Dương soát) → trang Cảnh báo L2 (phần BE); xuất file OpenAPI | Đo bộ nhớ, p95 (lúc agent ở DỪNG); validation + phép thử LLM chấm; chạy `b2_review_offline.py`, `b3_offline.py`; tính lại báo nhầm `requester_probe` cho Dương |
| T3 20/10 | Sáng: chấm `p_mal` câu kịch bản demo và gate. 12:00 mốc quyết (gói 1, τ, bộ nhớ, LLM chấm, nhãn che B3); chiều gói 3 nếu LLM chấm mới đạt, commit TRƯỚC khi gộp 2b | Rebase lên gói 1 → dòng lịch sử L2; tối gộp 2b sau khi gói 3 commit | Phiên FE làm trang Cảnh báo cho L2; gửi tin GVHD SAU mốc 12:00; tối: gộp 2b → lượt verify các PR sau 18:10 (cũng là chạy thử bản đã gộp) → đo lại B2 |
| T4 21/10 | 14:00 `make verify G=2345` trên commit đã đặt `review` + `B2_TAU_REVIEW` (47–50 phút, đủ một vòng sửa) rồi gộp; 18:00 cắt | — | Thứ tự gỡ khi đỏ: B3-VA → gói 2 → dòng lịch sử của 2b → gói 1 |

Không cắt việc theo kế hoạch: phần nào chưa xanh lúc 14:00 21/10 thì không gộp phần đó.

**Ràng buộc:**
- Không đụng M5 (D-43), `risk/*`, B12, B17.
- `audit/handoff.py` chỉ gói 1 sửa; 2b và B3-VA đi qua `escalation_note`.
- Không sửa prompt `b03_classify`.
- Giữ luật git 4.0 (mục 0.2).
- Việc treo "tải song song" ở 7.12 vẫn mở: hàng chờ riêng của gói 1 chỉ tách classify khỏi embed/rerank, không xử lý quá tải ở B8.
- **Luật dùng stack 18–21/10:** chỉ chạy stack trên commit đã có (ghi SHA), lúc mọi agent đang đứng ở DỪNG; không chạy hai việc đo cùng lúc trên máy Tuấn Anh. Compose `name: servicedesk` cố định nên `make up` ở worktree nào cũng thay đúng các container đó; worktree 2b không `make up`.
- Sau khi 2b gộp, DB chung lên `0010`: nhánh `-m5` và PR chưa rebase không dựng stack được tới khi rebase (phiên git báo Phase 6).
- F8 (sửa prompt) không đụng `b02_injection_judge`.
- **Số phiên song song [Chốt 18/10 03:25]:** tối đa 3 phiên coding agent trong 18–21/10 (thư mục chính, worktree 2b, 1 phiên cho việc F ở thư mục riêng do phiên git tạo); mỗi phiên một thư mục; phiên việc F không sửa file của gói 1 và 2b; sau 21/10 về lại 2.

**Spec cần sửa** (sau 18:00 21/10, qua phiên tài liệu):

| File | Sửa |
|---|---|
| `B02` §1, §7 | Chế độ `review`; bảng quyết định; E1 `injection_suspected`; τ theo E_max; bộ từ thay nhãn che |
| `B03-B05` §2, §5.1, §10 | Đồng bộ theo bảng 5.2.2 (lệch từ T20b); B3 ghi điểm (D-53); bước "dính nhau" (D-55) |
| `B20` | Câu cảnh báo cho `injection_suspected`; dòng lịch sử người gửi; `escalation_note` của con không chắc |
| `P2` | Vai trò `judge` (nếu gói 3 làm) |
| `P4` | Hàng chờ riêng `ML_CLASSIFY_CONCURRENCY` (lệch 3a); `classify_failed`; classify không thử lại khi timeout; `ML_MODELS_ROOT`; `check_intent`; `IntentOut`; manifest + SHA bắt buộc |
| `P6` §5.1 | `alert:read` cho `l2`; `ALERT_ACK_ROLES`; giới hạn tần suất theo tài khoản (bộ tin nhắn gồm `/confirm`) |
| `P7` 2.3 + danh sách bảng | Loại sự kiện `rate_limited`; bảng thứ 23 `rate_hits` (đếm tin nhắn, không append-only, GRANT `app_rw`); migration `0010` (CHECK, index `tickets(requester_id, created_at)`, `rate_hits`, `v_leaf` thêm `requester_id`) |
| `P9` | Luật `requester_probe`, `requester_probe_critical`; nhãn người nhận `l2`; `v_leaf.requester_id`; định nghĩa lại luật 12; `e1_split` tách `injection_suspected` |
| `P10` | Trang Cảnh báo cho L2 (`can_ack`) |
| `P11` §4–5 | Ngưỡng `tau_review` ở `B2_TAU_REVIEW`, bản ghi `tai-lieu/thresholds.json` (lệch §4.3); chuyển gói intent sang safetensors fp32 (`v3.1-seed42-st/`) |

Việc của người khác (Dương, Duy Anh, phiên git, phiên FE, phiên B3-VA): xem `claude/dac-ta-bat-2-model.md` mục 12.

---

## 8. Lịch và thứ tự [làm mới 14/10]

| Ngày | Chặng | Tầng / DỪNG | Phụ thuộc | Phase 6 |
|---|---|---|---|---|
| 09/10 | ~~T22a~~ xong `2ffb005` | A / 2 | — | 6A gộp |
| 10/10 | ~~T23a~~ xong `a463150` | A / 1 | 6B gộp `d42d5c4` | 6B gộp |
| 11–12/10 | (FE PR #27/#35; K2 PR #29 gộp + ingest `6cf1091` 23:30 12/10) | — | — | — |
| 13/10 sáng | (Claude chat: spec T20a v0.3 — Tuấn Anh duyệt) | — | — | — |
| 13/10 | ~~T20a~~ xong `03b4450` (09:30) | A+B / 2 | `6cf1091` | — |
| 13/10 | ~~T24~~ xong `457239d` (CI xanh); PR #39 → main `e000d03`; PR #38 M9 A4 → `dev-tuananh` = `90ee85d` | A / 2 | `03b4450` | đã báo "6C mở được" (tin #10) |
| 13/10 tối | (Claude chat: spec T20b v0.5 — Q5 chốt) | — | — | — |
| 13–14/10 | ~~T20b~~ xong: DỪNG 1 `14316ad` (14/10 01:00), DỪNG 2 `5df24c7` + `8a7c697`, đẩy 14/10 (sớm 2 ngày) | A / 2 | `90ee85d` | 6C MẪU A 14 |
| 15 | Commit docs (spec v0.6 + D-49) qua phiên git; mutation lượt 2 T23a (khoá thư mục chính ~1,5 giờ, tầng B) | B | `8d2aa6e` | **6C DỪNG 1** |
| 16 | — | — | — | **6C DỪNG 2** → gộp (quyết 21:00) |
| ~~17~~ **15** | **Cổng 5 ĐẠT** — lượt chính thức `make verify G=2345` trên cây `5f2ece2` (gộp 6C; Tuấn Anh, 00:22–01:12) + thành viên trên máy riêng (Duy Anh, WSL 2, `60f89a6`, lượt 2 10:57–11:44): gate2 89/0, gate3 78/0 · 66/0 (theo giờ), gate4 73/0, gate5 227/0 | — | T22a–T24, T20b, 6C | 6C gộp `5f2ece2` |
| 18 | Chép tài liệu vào repo + commit (phiên git) → **Gói 1 DỪNG 1, DỪNG 2** (thư mục chính) · **Gói 2b** phần chống spam (worktree riêng) — mục 7.14 | A | DỪNG 3 đã push (`33b7484`); 4 điểm chờ đã chốt 03:25; phiên git khoá thư mục chính + tạo worktree 2b | — |
| 19 | **Gói 2** → **B3-VA** (thư mục chính, nối tiếp — cùng `b03_classify.py`) · 2b: luật M9 `requester_probe` (Dương soát), trang Cảnh báo cho L2 (BE) | A | gói 1 | — |
| 20 | 12:00 mốc quyết (gói 1, τ, bộ nhớ, judge, nhãn che B3) · **Gói 3** chiều nếu judge đạt, commit trước khi gộp 2b · 2b: dòng lịch sử L2, gộp 2b tối · FE: trang Cảnh báo cho L2 (từ file OpenAPI của 2b) | A | gói 1, 2 | — |
| 21 | 14:00 `make verify G=2345` trên commit đã đặt `review` + `B2_TAU_REVIEW`, rồi gộp · 18:00 cắt đổi hành vi | — | mọi gói | chốt strong + `p_method` trước 12:00 (D-51) |

Cổng 5 đạt khi: `make lint`, `make test` xanh; CI xanh; cổng 5 tự động đủ; mutation T22a/T23a/T24 ×2, T20a/T20b ×1 (phần A ×2); thành viên chạy `make verify` + biên bản; spec "Chốt khi hiện thực" từng chặng; `decisions.md` D-35, D-41, D-44…46. **Bỏ khỏi Phase 5 (D-44):** model phân loại của Duy + cascade B3 — làm sau cổng 5 khi có τ_hi/τ_lo + SHA.

## 9. Nhật ký

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 18/10/2026 | 0.14 | Mục 7.14 khớp đặc tả v0.6: Tuấn Anh chốt 4 điểm lúc 03:25 — bộ đếm tin nhắn gồm `/confirm`, đếm bằng bảng `rate_hits` (`0010`, bảng thứ 23); 3 luật đo ghi trước vào D-52; tối đa 3 phiên coding agent 18–21/10 (mục 0 và 0.2 ghi ngoại lệ); Claude chép tài liệu vào `docs/spec`. Mục 8 dòng 18 |
| 18/10/2026 | 0.13 | Mục 7.14 khớp đặc tả v0.5 (soát 3 người độc lập trên `33b7484`): gói 1 chia 2 DỪNG và thêm script chọn τ, chèn PII; τ qua `B2_TAU_REVIEW`; 2b test Postgres trong worktree, nới ngưỡng ở `verify.sh`, `v_leaf.requester_id`, 2 luật `requester_probe`; việc trước khi mở phiên; luật dùng stack; thứ tự tối 20/10; 7 điểm chờ duyệt. Mục 8 dòng 18, 20, 21 |
| 18/10/2026 | 0.12 | **Mục 7.14** (mới): sau cổng 5 — bật 2 model phân loại (B2 `review` D-52, B3 ghi điểm D-53), chống dò và spam (D-54), B3-VA (D-55); 5 gói, phép đo chốt trước, lịch 18–21/10 trên 2 worktree, "Spec cần sửa" sau 21/10. Bảng kế hoạch tóm tắt dòng 6–10; mục 8 thêm 18–21/10. Nguồn: `claude/dac-ta-bat-2-model.md` v0.4 (Tuấn Anh chốt rạng sáng 18/10) |
| 18/10/2026 | 0.11 | Mục 7.12 dòng 3: LLM-G DỪNG 3 `3cf0d18` — 3 prompt (`b03_classify@4`, `b10_need_type@2`, `b10_answer@2`), vpn-smoke 53/0 cấu hình A và B (NỢ-3-2 đóng), probe JSON 287/287, model chốt D-51; việc treo tải song song (4 ticket → E2 ở B8). Mục 7.13: **cổng 5 thủ công ĐẠT** — intent macro-F1 0,9399, chặn 14/15, chặn nhầm 0/30, E0 14/14, tách ý 10/10, ghi chú E7 đủ 4 phần; script đo + `make probe` |
| 17/10/2026 | 0.10 | Mục 1.3: cổng 5 thủ công 45 câu, macro-F1 5 lớp, bộ câu chỉ để đo (chốt 15/10). Mục 7.11: bảng S4 "mở rộng 1 → 4 loại tốn gì" (5 → 20 luật, 7 → 20 fact, 3 → 9 hành động, 0 tool/node/migration mới, 29 file code, 0 kịch bản VPN đổi kết quả). Mục 7.12: LLM-G (`0e74095` + `90deec7`). Mục **7.13**: phần thủ công cổng 5 còn nợ + quy tắc lượt đo |
| 16/10/2026 | 0.9 | Mục **7.12** (cập nhật tối 16/10: V17 `45f5cd7` + verify G=345; sửa cột "Thay chỗ" — P7 không có bảng mô tả luật): V16 (`68c7f7d` — dấu vết 401, `verify.sh` lưu log cổng đỏ + bước 9 theo HEAD; verify G=2345 xanh) và V17 (mô tả R17–R19 thêm "cần người duyệt" — P6→P5 #21); việc treo g4-10 |
| 16/10/2026 | 0.8 | **Cổng 5 ĐẠT 15/10** (lượt chính thức cây `5f2ece2` + Duy Anh `60f89a6`; xem `PROGRESS.md` mục "Phase 5 — Cổng 5 ĐẠT"); lịch mục 8; sửa gate2 `24c5012` (verify `1db4bd8` gate2 91/0); mốc main `a0606b1` (PR #48) |
| 14/10/2026 | 0.7 | Mục **7.11** chốt khi hiện thực T24 (viết bù từ `PROGRESS.md` mục T24: Q-T24-1…11, đổi tên `PlanExecutor`, nợ compose `ENABLED_INTENTS` + NGHI-1) — đủ "Chốt khi hiện thực" 5 chặng cho cổng 5 |
| 14/10/2026 | 0.6 | **T20b đóng** (`14316ad` + `5df24c7` + `8a7c697`, verify G=2345 lần 3 + G=5 xanh, đẩy 14/10); mục 5.2.13 chốt khi hiện thực (Q-T20b-1…13: wiring 2 dòng, ý lẫn ra mã của ý đầu, hạn cha thay 2 loại, cha lỗi có escalation — lệch D-30 có chủ đích, mốc `deliver`, P12 trong `scan_deadlines` + hạn thường cho con mồ côi, `/reply` che qua helper, B3 chạy lại lệch → E9, `audit_check` điểm 8 cho cha); nợ + dồn mốc G; lịch: 6C DỪNG 15/16, cổng 5 ~17/10 |
| 13/10/2026 | 0.5 | T24 đóng (`216c89d` + `457239d`); **mục 5.2 T20b viết đủ** trên code `90ee85d`: Q5 = con vào B6 (seed từ B3 cha, không chạy lại B1–B3), ý lẫn = tách (ý không chạy được → con E1, `split_span_invalid` mới), B5 hai pha + `ChildOps` ở runner, notifier ghi `child_notices` + con không đặt hạn, `after_turn` đánh thức khi con dừng ở node chờ, `parent_wait`/`parent_reply_wait` thật, `compose_digest` + bảng đóng cha (+ tổ hợp đủ 3 loại [Đề xuất]), `POST /reply` + `children_progress`, lưới an toàn worker, preset con `<thẻ>-<i>`, gate5 5 kịch bản nhiều ý, ~55 ca test, 14 mutation, 10 mục soát; không migration; `wiring.py` 1 dòng; lịch: T20b DỪNG 15/16, 6C DỪNG 17/18, cổng 5 ~19–20 |
| 13/10/2026 | 0.4 | T20a đóng (`52c8349` + `03b4450`); 5.1.11 chốt khi hiện thực (Q-T20a-4/6 cờ `target_is_other` ở B3 + `clarify_wait`, 17 mutation, D1 none 14/40, nợ); **mục 7 T24 viết đủ** (PLAN 6 hành động + bước license có điều kiện, `PlanExecutor` hoàn tác theo bước, B18 6 mẫu, ghi chú bàn giao theo hành động, registry ghi 4 hệ thống, bật 4 intent, `make gate5` 9 kịch bản, 12 mutation); lịch: T24 13 chiều–15 |
| 13/10/2026 | 0.3 | **T20a viết đủ** (mục 5.1: 12 P-x, bảng tool → fact, hợp đồng `PARAMS_BY_ACTION`, ~70 ca test, 14 mutation, 9 mục soát, 2 DỪNG) trên code `6cf1091`; access thêm slot `target_user` (R12 chạm được đầu-cuối) [Đề xuất]; áp 17 mục "Spec cần sửa (T22a)" (4.13 → 4.14 + sửa tại chỗ) và 11 mục T23a (6.5); T23a đóng; lịch mục 8 (T20a 13–14) |
| 10/10/2026 | 0.2 | T22a đóng (`2ffb005`). Kế hoạch sau T22a theo phiên PHAN-TICH-P5 (soát code chỉ đọc) + Tuấn Anh chốt: mục 5 tách T20a/T20b (ước 19–25 giờ, bật intent dời sang T24 — Q-5-7); mục 6 **T23a viết đủ** (đóng `ml-gan`, `shadow`, mặc định không nạp, 422 → L4 — Q-5-9, 9 mutation, `json_object` commit riêng); mục 7 T24 bật 4 intent; mục 8 lịch mới (cổng 5 ~20–21/10); model của Duy ra khỏi Phase 5 (D-44). 17 mục "Spec cần sửa (T22a)" CHƯA áp — làm 11–12/10 |
| 09/10/2026 | 0.1f (sửa 13:00) | Mục 0.2 viết lại theo luật git 4.0 (agent không tự pull/push/stack; phiếu cho phiên git), khoá thư mục chính tới hết DỪNG cuối, cấm ingest khi chặng mở, giao thức Phase 5–6 (2 agent, `PROGRESS.md`, `app.eval`, thứ tự 6B → T20, T24 → 6C); 0.1 thêm `RiskContext`, hằng `mutate_3h.py`; P5/P11 thêm cấm `risk/models.py`, `config/scripted`, `app.eval`; 4.9 thêm bất biến (8); 4.10 nêu bàn giao DỪNG 1 + phiếu push; T20 phụ thuộc 6B; lịch mục 8 theo lịch chung v0.6. **Lời mở chặng thắng mục 0.2 về thao tác git/stack** |
| 09/10/2026 | 0.1f (sửa 01:20) | Mục 0.2: khoá thư mục chính tới hết DỪNG 2 (commit + push); cấm `make ingest` khi chặng còn mở. Tuấn Anh chốt bảng 4.2 `procedure_doc` theo K2 thật (Q-5-6): `view_permissions` → KB-ACS-005, `grant_permission` → KB-ACS-001; sửa 4.11, dòng `test_s0_grounding` ở 4.7b, thêm ca h8; mốc `3ff63e1` (file T22a không đổi); 0.1 thêm dòng `approvers.yaml`; T20/T23 cập nhật đầu vào (`ml-gan`, K2 PR #29) |
| 06/10/2026 | 0.1e | Kiểm kỹ lần 3: dựng thử P7 (không vỡ test nào; chốt vị trí 3 trường ở model tool); sửa 2 `value_rules` sai (tên phần mềm, đường dẫn thư mục có chữ hoa); `target_lock_reason` theo giá trị thật của mock; K2 qua `load_kb` |
| 03/10/2026 | 0.1c | Rà soát lần 2: dựng thử lớp luật trên engine thật (57/57 ca đúng, khởi động qua, 7/12/1). Thêm mục 4.7b: 13 test cũ phải đổi + cách đổi; 4.5 thêm `domain/messages.py` (6 nhãn), `mutate_3h.py`; P7 thêm quy tắc `disable_reason` ở endpoint quản trị; v1 sửa lại phạm vi "không đổi kỳ vọng" |
| 01/10/2026 | 0.1 | Tạo file: sự thật code `aac90b1`; Q-5-1…5 chốt; T22a đủ (P1–P11, metadata 6 hành động, 12 fact, bảng 20 luật kèm điều kiện, `rule_coverage.py`, ≥ 60 test, 12 mutation, checklist Quân); T20, T23, T24 mức khung |
