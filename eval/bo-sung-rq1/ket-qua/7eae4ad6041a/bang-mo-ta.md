# Bảng mô tả — đo bổ sung RQ1, lượt 7eae4ad6041a

**Mô tả sau khi thấy số** (GHI-TRUOC.md mục 10, phần 19/11 khoảng 18:00, ý 7). Không đổi số đã ghi ở ý 5.

- Lập: Dương, máy đo, T5 19/11/2026 khoảng 23:55. Không chép câu người dùng; chỉ mã thẻ, tên trường và số.
- Lượt: run_id `7eae4ad6041a`, worktree `do-bo-sung-rq1` @ `9d2e786`, `dataset_sha256` `ad8ad99e…ffdd`, `predictions.jsonl` sha256 `2b4e527d0c54…`.
- Truy vấn audit DB: chỉ đọc (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`), chỉ bật postgres, lọc theo ticket của lượt; điều phối duyệt 19/11 23:46.
- Nguồn: [CT] `phan-tich/chi-tiet.csv` · [PR] `s1-moi/predictions.jsonl` · [OC] `s1-moi/outcomes.jsonl` · [MF] `s1-moi/manifest.json` · [AU] bảng `audit_logs` · [TK] bảng `tickets` · [LOG] `s1-moi-ml.log` (log backend + worker) · [THE] `eval/bo-sung-rq1/the/` @ `9d2e786`.

## 1. 4 lá AUTO và 2 lá cần người có p = 0,2

| scenario_id | Nhãn cuối [CT `expected_route`] | Route hệ thống [CT `route`] | p thô [CT `raw_prob`] | `kb_gap` [CT] | Yếu tố rủi ro [AU `B13/B14` `risk_decided` `detail.factors`] |
|---|---|---|---|---|---|
| SB41-q1 | AUTO | ESCALATE_L2 | 0,8 | False | `routine_low_risk`, `missing_facts`, `no_policy_evidence` |
| SB42-q1 | AUTO | ESCALATE_L2 | 1,0 | False | `missing_facts`, `no_policy_evidence`, `long_duration`, `routine_low_risk`, `sensitive_data` |
| SB43-q1 | AUTO | ESCALATE_L2 | 1,0 | True | `missing_facts`, `no_policy_evidence`, `privileged_target` |
| SB44-q1 | AUTO | ESCALATE_L2 | 1,0 | True | `missing_facts`, `no_policy_evidence`, `privileged_target` |
| SB10-q1 | ESCALATE_L2 | HITL | 0,2 | True | `no_policy_evidence`, `routine_low_risk`, `target_is_other`, `missing_facts` |
| SB31-q1 | HITL | HITL | 0,2 | True | `no_policy_evidence`, `routine_low_risk`, `target_is_other`, `missing_facts` |

Thứ tự yếu tố giữ như trong log. Cả 6 lá đều có `missing_facts` và `no_policy_evidence`.

## 2. Tỉ lệ `kb_gap` trên 26 lá

- **18/26 lá `kb_gap = True` (69%)**. 8 lá False: SB15, SB26, SB27, SB29, SB39, SB40, SB41, SB42. [CT `kb_gap`]
- 26 lá = bộ mới chính: 43 bản ghi [PR] − 10 `khong_toi_m5` − 7 `luat_quyet` (GHI-TRUOC.md dòng 273). Nhãn: cần người 22 (HITL 18, ESCALATE_L2 4) / AUTO 4. [CT `expected_route`]

## 3. 10 lá không tới M5 (`khong_toi_m5`)

| Loại | Số | Lá | Nguồn |
|---|---|---|---|
| E1 — dừng ở B2, nghi tấn công | 3 | SB07-q1, SB20-q1, SB21-q1 | [AU] `step B2`, `event injection_suspected`, `exit_code E1`, rồi `B20 closed E1`; [PR] `intent` null (khớp [MF] `counts.intent_missing 3`) |
| E2 — tool/RAG lỗi hệ thống sau retry | 3 | SB12-q1, SB16-q1, SB17-q1 | [PR] `exit_code`, `route` null |
| E3 — không có căn cứ (NO_EVIDENCE) | 2 | SB03-q1, SB30-q1 | [PR] `exit_code`, `route` null |
| timeout 300 s | 1 | SB18-q1 | [OC] `outcome timeout`, 301,4 s; [PR] `final_state` null |
| tự giải quyết qua KB | 1 | SB19-q1 | [PR] `final_state S_RESOLVED`, `resolution_path deflected`, `close_reason resolved_user_confirmed` |

Nghĩa mã: `backend/app/domain/exit_codes.py:11–15` @ `bf94df2`. B2 cũng trả E1 (`backend/app/guard/b2_review.py:53`).

## 4. 7 lá do luật quyết (`luat_quyet`)

| scenario_id | `decided_by` [AU] | Mã luật [AU `matched_rule_id`, `all_matched`] | Hành động hệ thống dựng [AU `intended_action.type`, dòng mới nhất] | Hành động trên thẻ [THE `gold.action.type`] | Route [PR] | `exit_code` [PR] | Kết cục [PR] |
|---|---|---|---|---|---|---|---|
| SB01-q1 | rule | R09 | `grant_permission` (B15 queued) | `grant_permission` | HITL | — | `S_REJECTED`, `rejected_by_approver` |
| SB04-q1 | rule | R09 | `grant_permission` (B15 queued) | `grant_permission` | HITL | — | `S_REJECTED`, `rejected_by_approver` |
| SB13-q1 | rule | R13 | `install_software` (B11 action_built) | `install_software` | HITL | E5 | `S_ESCALATED` |
| SB24-q1 | rule | R13 | `install_software` (B11 action_built) | `install_software` | HITL | E5 | `S_ESCALATED` |
| SB25-q1 | rule | R13 | `install_software` (B11 action_built) | `install_software` | HITL | E5 | `S_ESCALATED` |
| SB37-q1 | rule | R13 | `install_software` (B11 action_built) | `install_software` | HITL | E5 | `S_ESCALATED` |
| SB38-q1 | rule | R13 | `install_software` (B11 action_built) | `install_software` | HITL | E5 | `S_ESCALATED` |

- Mỗi lá chỉ khớp 1 luật (`all_matched` 1 phần tử). Nhãn cuối cả 7: HITL. [CT/PR `expected_route`]
- **Loại hành động hệ thống dựng trùng loại trên thẻ ở cả 7 lá.** Ý 7 ghi "lúc chạy, hệ thống dựng hành động khác thẻ": ở mức loại hành động thì không thấy khác. Phần khác (nếu có) nằm ở đích, tham số hoặc dữ kiện của hành động: **không có trong phạm vi truy vấn đã duyệt**, không kiểm.

## 5. Thẻ `multi_leaf`

- **SB02-q1: 2 lá con.** [TK] `count(*) WHERE parent_ticket_id = <ticket SB02>` = 2; [AU] `step B5`, `event split_into_2_children`.
- [OC] `outcome multi_leaf`, 36,3 s; không có dòng [PR] ([MF] `counts.multi_leaf 1`, `written 43`).
- `detail.children` ở B5 không phải mảng nên không đếm được theo trường này; số lá lấy theo [TK].

## 6. Nguồn số `ml_error`

| Mục | Giá trị | Nguồn |
|---|---|---|
| Số lỗi | **4** lần `/classify` lỗi, đều `error=timeout` | [LOG] dòng `ml:classify … error=timeout` (15:38:08–16:05:05), đếm bằng `~/eval-runs/rq1/so-chay/tong-luot.py` |
| Số lần gọi `/classify` | **44** (40 thành công + 4 lỗi; 1 lần/thẻ) | [LOG] |
| Tỉ lệ | **4/44 = 9,1% — vượt 5%** (quy tắc T2: Project `claude/dieu-phoi/d4-buoc2-s3-lan3-tra-12-ca.md`, mục "Quy tắc chạy T2 02/11") | tính từ 2 dòng trên |
| Lá | SB01-q1, SB13-q1, SB17-q1, SB18-q1 | [LOG] |
| Trong 26 lá chính | **0/26** (SB01, SB13 thuộc luật quyết; SB17 là E2; SB18 timeout) | đối chiếu mục 3, 4 |
| `manifest.json` `counts` | không có trong file (không có trường ml_error) | [MF] |
| `predictions.jsonl`, `ket-qua.json` | không có trong file | [PR], `ket-qua.json` |
| `so-chay.md` | không ghi ml_error | `~/eval-runs/bo-sung-rq1/so-chay.md` |
| Audit B2 | có khoá `detail.screening.ml_error`; giá trị theo lá không truy vấn (ngoài phạm vi đã duyệt) | [AU] (chỉ tên khoá) |

## 7. `git_dirty` và `commit_verified`

| Trường | Giá trị | Giải thích | Nguồn |
|---|---|---|---|
| `git_dirty` | **false** | `git status --porcelain` của worktree lúc chạy rỗng, kể cả file chưa theo dõi (liên kết `.env` bị git bỏ qua; `models`, `ml_models` nối qua biến compose). | [MF] `git_dirty`; `backend/app/eval/runner.py:152,163` |
| `commit_verified` | **true** | Runner so `APP_GIT_SHA` của container với HEAD của repo chạy runner và thấy khớp (`9d2e78681b18…`); lệch thì dừng mã 2, thiếu thì `false` kèm cảnh báo. | [MF] `commit_verified`, `app_git_sha`, `git_commit`; `runner.py:364–368, 527`; `so-chay.md` dòng (3) |
