# scripts/sim — chạy dữ liệu thử 3 cách xử lý M5 (D-67, P6 gói tuần 8)

`chay_thu_phuong_an.py` sinh ticket **dữ liệu thử** (`tickets.source = 'sim'`) cho tab "So sánh phương án"
(`GET /api/dashboard/strategies?source=sim`). Chỉ chạy trên stack **dev/test** của chính máy mình.

## Cần có

- Stack dev đang chạy (`make up`, `make seed`), backend ở `http://127.0.0.1:8000`, `APP_ENV=dev` (hoặc `test`).
- Tài khoản quản lý `quan.tm` đã đăng ký MFA (`python -m app.auth.mfa enroll quan.tm --by <bạn> --reason "chạy thử"`).
- Biến môi trường ở shell chạy script (KHÔNG ghi vào file, KHÔNG dán vào chat):
  - `APP_ENV=dev` — script từ chối chạy nếu thiếu hoặc khác `dev`/`test`;
  - `SIM_MANAGER_TOTP_SECRET` — secret TOTP của `quan.tm` (script tự tính OTP). Không đặt → script **hỏi OTP** mỗi lần đổi cách
    xử lý (4 lần — đăng nhập lại trước mỗi lần đổi vì cần đăng nhập gần đây);
  - `SIM_PASSWORD` — tuỳ chọn; không đặt thì dùng mật khẩu demo công khai của seed mock.

## Chạy

```sh
APP_ENV=dev uv run python scripts/sim/chay_thu_phuong_an.py --tagged
```

- `--tagged` thêm thẻ `[fake:<preset>]` cuối câu — **bắt buộc khi stack chạy `LLM_BACKEND=scripted`** (không có thẻ thì ScriptedLLM
  dùng preset `default` và kết quả không đúng nhóm câu). Với LLM thật (mốc G) thì bỏ `--tagged`.
- `--no-mock-reset` — không reset mock giữa các vòng (mặc định có reset: `docker compose exec -T mock python -m app.seed reset`, như
  gate, để "cài Zoom" / "đặt lại mật khẩu" chạy lại được ở vòng sau).
- `--url` — chỉ nhận localhost.

## Script làm gì

1. Đổi cách xử lý lần lượt `rule_only` → `hybrid` → `hybrid_guarded` (lý do "chạy dữ liệu thử").
2. Mỗi cách: nhân viên `an.nv` gửi cùng 8 yêu cầu kèm header `X-Sim-Run`:

   | Nhóm | Câu (nguồn) |
   |---|---|
   | Câu hỏi KB | TC04, TC05 (`backend/tests/stack/gate3.py`) |
   | Luật cho tự làm | TC01 R01, TC03 R11 (`backend/tests/stack/gate5.py`) |
   | Cần duyệt | TC07 R03, TC17 R13 (`gate5.py`) |
   | Không luật nào khớp | 2 câu TC37 (`backend/tests/unit/test_chain_m5.py`), preset dev-only `config/scripted/sim_khongluat.yaml` |

3. L1 `ha.lt` duyệt TC07, từ chối TC17. Nhân viên xác nhận TC04 và TC01 "Đã ổn", TC03 "Chưa ổn". Các ticket khác để nguyên.
0. Trước mọi thay đổi: đăng nhập quản lý, đọc cách xử lý hiện hành (lưu làm "ban đầu"). Server đang `EVAL_MODE` → dừng ngay
   (mã 3), không đổi gì.
4. Cuối cùng (kể cả khi lỗi giữa chừng): cách xử lý hiện hành khác "ban đầu" → đặt lại "ban đầu" (lý do "khôi phục sau chạy thử dữ
   liệu thử"); đã bằng thì không đổi gì. Không khôi phục được → script in CẢNH BÁO: tự đặt lại ở màn Chính sách.
5. `source = 'sim'` của ticket chỉ kiểm được ở PG (API ticket không trả `source`):
   `SELECT source, count(*) FROM tickets WHERE created_at > <lúc chạy> GROUP BY 1`.

Script chỉ in số ticket theo từng cách (và mã HTTP khi lỗi) — không in câu chữ, token, mật khẩu, OTP.
Mã thoát: 0 xong, 1 dừng giữa chừng / chưa khôi phục được, 2 từ chối chạy (APP_ENV/URL), 3 server đang EVAL_MODE.
