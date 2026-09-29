B2 — chuẩn hoá, privacy guard, mẫu injection, phân loại injection. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- `privacy.py` (2b-3, thật từ 3e): port `PrivacyGuard`, `RedactionResult` (B02 mục 4, 3e thêm `pii_found`).
  `RegexPrivacyGuard` (L1, KHÔNG dùng Presidio — 3-Q22): L0 rồi 10 luật của `config/privacy_patterns.json` đúng thứ tự
  (bí mật → `[BÍ_MẬT_ĐÃ_ẨN]`; PII → `<LOẠI_n>`, cùng giá trị → cùng nhãn; không lưu ánh xạ). `NotRedactingGuard` chỉ
  nạp khi `PRIVACY_GUARD=none` VÀ `APP_ENV` ∈ {dev, test} (`main._default_guard`); mặc định mọi env là regex.
- `normalize.py` (3e): L0 riêng của guard — `core.normalize` → NFKC → xoá ký tự `Cf` (zero-width, soft hyphen, word
  joiner…). `match_forms` cho L2: {có dấu, không dấu `unidecode`} × {giữ, gộp xuống dòng}. `core.normalize` không đổi
  (ingest dùng).
- `patterns.py` (3e): nạp + biên dịch hai file mẫu (Pydantic `extra=forbid`); sai → `PatternFileError` → backend và
  worker không khởi động (`check_guard`, gọi trước khi đụng DB). Không có mẫu mặc định trong code.
- `injection.py` (3e): L2 `match(text)` → `ScreenHit(id, group)` | None; `TAU_BLOCK` 0,90 / `TAU_PASS` 0,10 cho L3.
- `screen.py` (3e): `screen_reply` = L0 + L2 cho tin trả lời ở `clarify_wait` / `confirm_wait` (3-Q3 phương án A).

Điểm áp L1 (API, trước khi lưu hay đưa vào graph): `POST /api/tickets`, `/messages`, `/confirm` (`note`),
`/approvals/{id}/decision` (`note`). Guard lỗi → 503 `privacy_guard_unavailable`, không INSERT. L2–L4 chạy trong node
`graph/nodes/b02_screen.py`. Test: `unit/test_guard_{privacy,injection,api}.py`, `integration/test_guard_pg.py` (e9
canary quét mọi bảng); mutation `scripts/mutation/mutate_3e.py`.

Ô đầu vào KHÔNG qua guard mà được lưu phải là mã cố định hoặc định danh chặt (PLAN-3e Q-3e-13, rà trường tự do):
`DecisionIn.reason_code` = enum `ReasonCode`, `LoginIn.username` = `USERNAME_PATTERN`. Thêm route có ô chữ tự do
(ghi chú L2 `/reply`, lý do ghi đè `/override`) → đi qua `api/desk.redact` + `record_redacted`.
