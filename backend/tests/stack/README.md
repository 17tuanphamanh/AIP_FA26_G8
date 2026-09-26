# Cổng 2 trên stack compose thật (2b-4)

`gate2.py` chạy trên máy dev, nói chuyện với backend `http://127.0.0.1:8000` và Postgres của compose
(psql **trong** container postgres). Không nằm trong `make test`.

## Chuẩn bị (một lần)

1. `.env` có `APP_ENV=dev`, `FAKE_APPROVER_ID=l1_01`, `FAKE_SCENARIO=approval`, `FAKE_NODE_DELAY=40`
   (mẫu và giải thích ở `.env.example`).
2. `make up` (build lại image — code 2b-4 nằm trong image).

## Chạy

```
make gate2 S=preflight      # kiểm stack + thẻ [fake:…] có hiệu lực
make gate2 S=restart        # hoặc late, expire, late-click, kill, kill-b15, tc29, threads, restart-all
make gate2 S=all            # mọi kịch bản trừ restart-all (~10 phút: kill + kill-b15 chờ worker phục hồi)
```

Script tự chạy lệnh compose cần thiết (`restart`, `stop/start worker`, `kill -s SIGKILL backend`,
`up -d backend`, `down` + `make up` cho `restart-all`) và **in từng lệnh trước khi chạy**.

**Chốt an toàn** (trước mọi việc khác): APP_ENV của container backend phải là `dev`; URL chỉ `127.0.0.1`;
cấm `down -v` / `--volumes` / `volume rm|prune`. Không qua → `DỪNG (chốt an toàn)`, exit 2.

Mật khẩu demo: `GATE2_PASSWORD` nếu đặt, không thì hằng `tests/fakes/demo.py` (mật khẩu công khai của mock).

## Đọc kết quả

Mỗi dòng: `PASS|FAIL <ticket_id> <tên kiểm>: mong đợi …, thấy …`. Cuối: tổng PASS/FAIL, liệt kê lại các
FAIL; exit 1 nếu có FAIL. Kiểm trên tập dòng rỗng luôn là FAIL; "không có X" chỉ PASS khi đối chứng "có Y"
của cùng ticket khác rỗng.

| Kịch bản | Đạt khi | FAIL thường nghĩa là |
|---|---|---|
| `preflight` | health `runtime: up`, worker `healthy`, ticket `[fake:clarify]` tới `S_CLARIFYING` | ticket về `S_PENDING_APPROVAL` → `.env` thiếu `FAKE_SCENARIO` hoặc chưa `make up` lại |
| `restart` | sau `restart backend`: duyệt → B16 `approved` rồi B17 `execution_failed` = **E7 do RefusingExecutor (dung toi Phase 3)**; clarify trả lời → chờ duyệt, B11 `asked` 1 lần; confirm → `resolved_user_confirmed` | clarify hỏi lại → kết quả node giả lấy từ bộ nhớ process thay vì state |
| `restart-all` | như `restart` sau `down` (giữ volume) + `make up`; số ticket trước/sau bằng nhau | số ticket lệch → mất volume |
| `late` | sự kiện sai loại ở 3 trạng thái chờ → 409, trạng thái giữ nguyên, đúng 1 `late_event` `source=user` | 2 dòng `late_event` → guard ghi trùng |
| `expire` | dời hạn về quá khứ → ≤ 45 giây: E6 + phiếu `timeout`; E4; `resolved_auto_timeout_48h`; 0 dòng B17 | quá 45 giây → worker không quét hạn |
| `late-click` | worker dừng: bấm muộn → 409, phiếu vẫn `pending`, `late_event reason=expired`; worker chạy lại → E6, `timeout`; bấm lại → `already_decided` | phiếu đổi trước khi worker quét → lệch 2b-3-Q2 |
| `kill` | SIGKILL backend khi đang ngủ ở b06 → khoá advisory của ticket nhả ≤ 10 giây; worker phục hồi (≤ 6 phút) → chờ duyệt, cùng `turn_id`, `recover_attempts=1`, 1 phiếu, audit không trùng | khoá còn → kết nối chết chưa nhả; audit/phiếu trùng → hỏng idempotent |
| `kill-b15` | như `kill`, chết ngay sau `approval_create` → 1 phiếu, 1 `approval_create`, 1 `notify_approver` | 2 phiếu → `effects.once` hỏng |
| `tc29` | `[fake:raise]` → E9, audit + span có traceback; 5 ticket song song tới chờ duyệt; worker healthy | — |
| `threads` | bảng ticket ↔ thread ↔ số checkpoint; mỗi ticket gate2 đúng 1 thread; không thread lạ | người đọc bảng, xác nhận mục thủ công của cổng 2 |
