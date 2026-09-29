Theo dõi toàn bộ việc xây **tầng Monitor M9 (backend)**, chia hai luồng chạy song song. Tuấn Anh review cuối + merge.

| Luồng | Người | Nhánh | Chặng |
|---|---|---|---|
| **A — Dashboard & dữ liệu đọc** | __ASSIGNEE_A__ | `m9-luuduong` | A0 → A4 |
| **B — Cảnh báo** | __ASSIGNEE_B__ | `m9-duyanh` | B0 → B3 |

**Đọc trước (cả hai):** `docs/spec/claude/ke-hoach-m9-chia-viec.md` (ai làm gì, chủ file, hợp đồng hàm, thứ tự merge) · `docs/spec/claude/ke-hoach-m9-monitor.md` (tham chiếu kỹ thuật: công thức, 16 luật, Q-M9) · `docs/spec/build/nen-tang/P9-monitor-M9.md` · `CLAUDE.md`.

**Không được phá:** M9 **chỉ đọc** (engine `app_monitor`, không fallback `app_rw`) · cảnh báo chỉ **báo người** · mọi chỉ số/luật đếm **ticket lá** (D-30) · nguồn chưa có → `unavailable`/`skipped`, không trả 0 · ghi `alerts` chỉ qua `audit.AlertWriter` · **chỉ chủ file sửa file** (mục 2 file chia việc) · **chỉ Dương viết migration**.

## Luồng A — Lưu Dương

- [ ] #__A0__ A0 Nền chỉ-đọc (`app_monitor`, `window.py`, import-linter)
- [ ] #__A1__ A1 View SQL + chỉ số nghiệp vụ
- [ ] #__A2__ A2 Chỉ số AI/LLMOps
- [ ] #__A3__ A3 API dashboard + cảnh báo (ack)
- [ ] #__A4__ A4 Health LLM + hiệu năng + nghiệm thu

## Luồng B — Tạ Duy Anh

- [ ] #__B0__ B0 Khung luật thuần (rules, evaluator)
- [ ] #__B1__ B1 Luật theo sự kiện + job 60 giây
- [ ] #__B2__ B2 Luật tổng hợp + job giờ/ngày
- [ ] #__B3__ B3 Drift PSI (Nên có)

**Thứ tự merge bắt buộc:** A0 → (A1, B0) → (A2, B1) → (A3, B2) → A4 → B3. Sau mỗi merge, người còn lại rebase.

## Cổng chéo (người xác nhận không phải người làm)

- [ ] **Cổng A** (sau A4) — Duy Anh chạy theo mục 7.2 file chia việc, dán kết quả vào đây
- [ ] **Cổng B** (sau B2) — Dương chạy theo mục 7.2 file chia việc, dán kết quả vào đây

## Câu hỏi Tuấn Anh chốt (không trả lời = làm theo mặc định; chốt trước hết ngày 1)

- [ ] Q-M9-1 chia nhóm N3 cho escalation có trọng số → mặc định: theo điểm log 4
- [ ] Q-M9-2 múi giờ "ngày" → mặc định: `Asia/Ho_Chi_Minh`
- [ ] Q-M9-3 thêm luật 16 `execution_failed` (E7) → mặc định: **có**
- [ ] Q-M9-4 luật 5 `breaker_open`: span tool chưa ghi DB → mặc định: luật viết sẵn, để pending
- [ ] Q-M9-5 phạm vi `dashboard:read:own` của L1 → mặc định: `approvals.approver_id = user`
- [ ] Q-M9-6 luật 14 báo lại → mặc định: 1 lần/ngày
- [ ] Q-M9-7 health LLM → mặc định: không gọi LLM thật, chỉ báo cấu hình
- [ ] Q-M9-8 luật 9 `subject` (không có `token_family_id` trong sự kiện) → mặc định: `user_id`

## Nguồn dữ liệu đang pending (Tuấn Anh tick + tag người phụ trách khi luồng chính có)

- [ ] Điểm log 4 thật (Phase 4–6) — view sẵn (A)
- [ ] Ghi đè L1 (Phase 4) → `override_count` (A)
- [ ] B3 xuống LLM + phiên bản model (3f/3g) → `b3_llm_rate` (A), luật 13 (B)
- [ ] Span tool trong bảng `spans` → luật 5 (B)
- [ ] `policy_saved` (Phase 7) → luật 11 (B)
- [ ] Route xem phiếu ghi `first_viewed_at` (Phase 4) → luật 7 trên dữ liệu thật (B)
- [ ] Ticket nhiều ý (Phase 5) → `multi_intent_*` (A)

## Cập nhật hằng ngày (comment ở đây, trước 21:00)

```
[Dương|Duy Anh] <ngày>
Xong: …
Đang làm: …
Chặn bởi: không | chờ merge #… | chờ trả lời Q-…
```
