P5 — mock hệ thống ngoài (FastAPI), cổng 8100; seed.json là dữ liệu chốt. Xem docs/spec/build/01-kien-truc-project.md mục 3 và docs/spec/build/nen-tang/P5-tool-registry-mock.md mục 7.

## Chạy

- Trong compose: `make up` (tự nạp seed). Nạp lại seed và tắt mọi lỗi đang bơm: `make seed`.
- Mock nghe trong mạng compose; ra máy host chỉ qua `127.0.0.1:8100` (chỉ localhost) để xem màn `/console` (mục dưới). Gọi
  API có token từ máy thì vào container backend:
  `docker compose exec backend python -c "import httpx; print(httpx.get('http://mock:8100/health').json())"`.
- Test: `uv run pytest mock_services/tests -o pythonpath=mock_services` (có sẵn trong `make test`).

## Token dịch vụ (header `X-Service-Token`, D-03)

| Token (env) | Đọc | Ghi |
|---|---|---|
| `SVC_AGENT_TOKEN` | ✓ | 403 |
| `SVC_EXECUTOR_TOKEN` | ✓ | ✓ (duy nhất) |
| `SVC_WORKER_TOKEN` | 403 | 403 |
| thiếu / lạ | 401 | 401 |

Token rỗng, ngắn hơn 32 ký tự hoặc trùng nhau thì mọi endpoint cần token trả 503. `/health` và
`/_admin/*` không cần token.

## Dữ liệu demo

- Mật khẩu demo của **mọi** người dùng trong seed: `Demo@2026!` (công khai, chỉ cho mock).
  Seed chỉ lưu hash argon2id. Sinh hash mới: `echo 'mật-khẩu' | PYTHONPATH=mock_services uv run python -m app.seed hash`.
- Mốc thời gian trong seed là tương đối (`*_days_ago`, `expires_in_days`): "chứng chỉ hết hạn 3 ngày
  trước" luôn đúng dù chạy ngày nào.
- Ca dựng sẵn: D-15 (`nv004` disabled → người hưởng lợi `nv005` active), D-20 (`nv002` có `LAP-0417` đã
  đăng ký và `PC-0977` chưa đăng ký), TC06 (`nv001`, `LAP-0342`, cert hết hạn 3 ngày).

## Bơm lỗi (`/_admin/faults`)

```
POST   /_admin/faults      {"path_prefix": "/ad", "mode": "error", "status": 500}
                           mode: error (status 4xx/5xx) | timeout (504 sau delay_ms, mặc định 30 s) | latency (chờ delay_ms rồi xử lý)
                           method: "GET"/"POST" (bỏ trống = mọi method); times: số lần (bỏ trống = tới khi tắt)
GET    /_admin/faults      liệt kê
DELETE /_admin/faults      tắt hết          DELETE /_admin/faults/{id}   tắt một
POST   /_admin/reset       nạp lại seed.json + tắt hết lỗi + xoá bộ đếm /_admin/calls
```

## Đếm lời gọi, đổi trạng thái người dùng (3h — `app/admin_calls.py`)

```
GET    /_admin/calls?path_prefix=/vpn/&method=POST   → {"count": n, "calls": [{"method", "path", "count", "statuses"}]}
POST   /_admin/calls/reset                            xoá bộ đếm
POST   /_admin/users/{user_id}/status  {"employment_status": "active|probation|disabled|terminated"}
```

Đếm ở NƠI NHẬN: middleware đếm nằm ngoài middleware bơm lỗi — request bị `/_admin/faults` trả 500, bị 401/403 vẫn được
đếm (lúc nhận, trước khi xử lý). Không đếm `/_admin/*` và `/health`. Test "gọi ghi đúng 1 lần" (e2e cổng 3, `make gate3`)
đọc số ở đây, không suy từ log của backend.

## Đặt lại mật khẩu qua SMS (F2)

```
POST /ad/users/{user_id}/reset-password   (token svc_executor)
     {"account_type": "ad", "channel": "email"}   mặc định — hành vi cũ: chỉ cập nhật password_last_set, 4 trường, mật khẩu cũ vẫn dùng được
     {"account_type": "ad", "channel": "sms"}     mật khẩu tạm một lần, hạn 15 phút (TEMP_PASSWORD_TTL)
POST /ad/change-password                  (token svc_executor)
     {"username", "temp_password", "new_password"}   new_password ≥ 12 ký tự, khác mật khẩu tạm
GET  /_admin/outbox                       tin SMS/email mock "đã gửi" — mật khẩu tạm ĐÃ CHE
```

- Số nhận lấy từ trường `phone` trong seed của **chính chủ tài khoản** (dạng `0900000xxx`, số giả). Body không nhận số điện thoại:
  trường lạ → 422. Người không có `phone` (`svc_backup`, `nv006`) → 409 `no_phone_on_file`.
- Chỉ tài khoản `ad` (mock chỉ có một mật khẩu để kiểm — mật khẩu AD): `account_type` khác → 409 `sms_reset_ad_only`.
- Sau reset SMS: mật khẩu cũ hỏng ngay; mock chỉ lưu hash argon2 của mật khẩu tạm + hạn. Gửi 1 SMS (có mật khẩu tạm) và 1 email
  báo chủ tài khoản ("có yêu cầu đặt lại mật khẩu qua SMS lúc …", số đã che — KHÔNG có mật khẩu). Phản hồi: 4 trường cũ với
  `delivered_via="sms"` + `expires_in_minutes`, không bao giờ có mật khẩu.
- `/ad/authenticate` bằng mật khẩu tạm còn hạn → 403 `password_change_required`; hết hạn hoặc đã đổi → 401 `invalid_credentials`.
- `/ad/change-password`: mật khẩu tạm đúng, còn hạn, chưa dùng → đặt mật khẩu mới; sai / hết hạn / dùng lần 2 / username lạ → cùng 401.
  Sau khi đổi: mật khẩu tạm và mật khẩu cũ đều hỏng, mật khẩu mới đăng nhập được.
- `POST /_admin/reset` xoá hộp thư đi và mọi trạng thái mật khẩu tạm (nạp lại seed).

## Mock-fidelity: phần mềm, license, VPN, thư mục chạy như hệ thống thật

Tên phần mềm (`/software/catalog|licenses/{name}`, `install`, `uninstall`): tra theo slug (`zoom`) trước, rồi theo tên hiển thị
hoặc `aliases` trong seed, đều sau chuẩn hoá (chữ thường, khoảng trắng → `-`): `Zoom Workplace`, `7-Zip`, `VS  Code`… Bảy tên trong
`kb/software/KB-SW-001.md` đều tra đúng mục; tên lạ vẫn 404. Seed kiểm lúc nạp (sai thì mock không khởi động): slug chỉ gồm
`a-z 0-9 -`; `display_name` không rỗng; slug, tên hiển thị và alias dùng chung một không gian tên — không trùng giữa các phần mềm,
không trùng nhau trong một mục, alias không rỗng và không lặp lại slug / tên hiển thị của chính nó.

```
GET  /software/licenses/{name}      thêm "assignments": [{"assignment_id", "user_id"}] — ai đang giữ (rỗng với phần mềm miễn phí;
                                    phần `used` dựng sẵn từ seed không có tên người giữ)
POST /software/licenses/{name}/assign              người này đã giữ license → 409 already_assigned (xét trước no_license_available)
POST /software/installed/{device_id}/install       phần mềm có phí mà CHỦ MÁY chưa giữ license → 409 license_not_assigned
                                                   đã cài rồi → 200 + "already_installed": true + phiên bản ĐANG cài (không cài lại)
POST /software/installed/{device_id}/uninstall     thêm "license_released": license của chủ máy về kho (used -1, bỏ khỏi assignments);
                                                   chỉ khi chủ máy hết cài phần mềm đó trên mọi máy của mình
POST /vpn/connect  {"user_id", "device_id"}        (token svc_executor) kết nối thử, ghi vào /vpn/connections/{user_id}
     → 200 {"at", "user_id", "device_id", "result": "success"|"failed", "error_code"}
POST /files/permissions/{user_id}/grant|extend     người không còn dùng được tài khoản → 409 user_not_active
POST /files/permissions/{user_id}/grant            thêm "previous_level", "kept_higher_level"
```

`/vpn/connect` xét lần lượt: máy chưa đăng ký → `DEVICE_NOT_REGISTERED`; máy không có chứng chỉ nào → `NO_CERT`; có chứng chỉ còn hạn
chưa thu hồi → `success`; còn chứng chỉ hết hạn chưa thu hồi → `CERT_EXPIRED`; chỉ còn chứng chỉ đã thu hồi → `CERT_REVOKED`
(mã đã có trong seed). Thiết bị không có / không thuộc `user_id` → 404; không đổi chứng chỉ nào (renew/reissue/revoke giữ nguyên).

Grant không hạ quyền: người đang có quyền CÒN HẠN cao hơn mức xin (`read` < `write` < `full`) → giữ nguyên mức và hạn,
trả `kept_higher_level=true` và `previous_level` là mức đang giữ. Xin mức bằng/cao hơn, hoặc quyền cũ đã hết hạn → thay bằng
quyền mới, `previous_level` là mức cũ (`null` nếu chưa có). "Dùng được tài khoản" = `employment_status` ∈ {`active`, `probation`}
(cùng tập `target_user_status` của `config/policy.json`); `disabled`/`terminated` → 409. `revoke` và `restore-expiry` không bị chặn.

### Mã lỗi mới (đều là `{"detail": "<mã>"}`)

| Endpoint | HTTP | Mã | Khi nào |
|---|---|---|---|
| `POST /software/licenses/{name}/assign` | 409 | `already_assigned` | người này đã giữ license phần mềm đó |
| `POST /software/installed/{device_id}/install` | 409 | `license_not_assigned` | phần mềm có phí, chủ máy chưa giữ license |
| `POST /files/permissions/{user_id}/grant` | 409 | `user_not_active` | `disabled` / `terminated` |
| `POST /files/permissions/{user_id}/extend` | 409 | `user_not_active` | như trên (quyền đang có vẫn nguyên) |
| `POST /vpn/connect` | 200 | `error_code` = `CERT_EXPIRED` · `NO_CERT` · `DEVICE_NOT_REGISTERED` · `CERT_REVOKED` | kết quả `failed` của lần kết nối thử (không phải lỗi HTTP) |

Mã 409 cũ giữ nguyên: `not_a_paid_license`, `no_license_available` (assign), `device_not_registered` (renew/reissue), `no_phone_on_file`,
`sms_reset_ad_only` (reset mật khẩu).

## Màn xem trạng thái (`/console`, `app/console.py`)

HTML dựng ở server, tự làm mới 5 giây, **chỉ đọc**, để demo "trước/sau" khi agent xử lý ticket. Mỗi trang có giờ VN (UTC+7) và
dòng **MÔI TRƯỜNG GIẢ LẬP**. Chỉ phục vụ khi `APP_ENV` là `dev` hoặc `test` (compose truyền `APP_ENV` vào container `mock`);
thiếu hoặc giá trị khác → **404**. Không cần token (trình duyệt không gắn được header) — rào là `APP_ENV` + cổng chỉ bind localhost.

| URL (`http://127.0.0.1:8100…`) | Nội dung |
|---|---|
| `/console` | mục lục + link điện thoại từng nhân viên |
| `/console/ad` | user_id, tên, email (chưa có trong state → "—"), SĐT che, trạng thái, khoá, password_last_set, phải đổi mật khẩu, có mật khẩu tạm còn hạn (có/không — không hiện mật khẩu) |
| `/console/vpn` | chứng chỉ (hạn, trạng thái), kết nối gần nhất mỗi người/máy |
| `/console/fileserver` | quyền, mức, hạn, độ nhạy thư mục |
| `/console/software` | máy → phần mềm đã cài; license còn lại + người giữ (chỉ có khi license cấp qua `assign`; seed không ghi người giữ → "—") |
| `/console/outbox` | tin SMS/email, mật khẩu tạm **đã che** |
| `/console/phone/{user_id}` | "điện thoại của nhân viên": SMS gửi tới số của **đúng** user đó, **hiện mật khẩu tạm** — trang duy nhất làm vậy |
| `/console/calls` | lời gọi tới mock theo endpoint + mã trả về (bộ đếm không lưu thời điểm; lời gọi `/console` bị ẩn) |

Lưu ý: lời gọi `/console/*` vẫn được `/_admin/calls` đếm (middleware đếm nằm ngoài) — lọc theo `path_prefix` khi đọc số liệu.
`POST /_admin/faults` với `path_prefix` bao cả `/console` (ví dụ `/`) cũng làm hỏng màn này.

## Giới hạn

- **SIM swap**: kẻ chiếm được SIM (đổi SIM, chuyển mạng trái phép) sẽ nhận được mật khẩu tạm qua SMS. Giảm thiểu trong mock: email
  báo chủ tài khoản ở mỗi lần đặt lại qua SMS, hạn 15 phút, chỉ dùng một lần và bắt đổi mật khẩu ngay. Không loại bỏ được rủi ro này —
  SMS là kênh yếu hơn email.
- Mock không gửi tin thật: SMS/email chỉ nằm trong hộp thư đi (bộ nhớ) và mất khi `/_admin/reset` hoặc khởi động lại.
- Phần mềm: tên không phải slug / tên hiển thị / alias trong seed vẫn 404. `used` dựng sẵn từ seed không có tên người giữ nên gỡ phần mềm có phí cài từ trước không trả license nào về kho.
- Backend hiện chỉ gọi kênh email; chưa có tool cho `/ad/change-password` và chưa xử lý 403 `password_change_required` ở đăng nhập.

## Bảng mong đợi — 12 tool đọc với seed (cổng 1, người xác nhận gọi tay)

Test tự động của bảng này: `backend/tests/e2e/test_tools_vs_mock.py` (registry thật → HTTP → mock).

| Tool | Tham số | Mong đợi |
|---|---|---|
| `check_account_status` | `nv007`, `account_type=email` | `account.locked=true`, `lock_reason=bad_password` |
| `check_lockout_history` | `nv007` / `nv002` | 3 lần khoá email, mới nhất trước / `[]` |
| `check_privilege_level` | `svc_backup` | `level=admin`, `is_privileged_account=true` |
| `check_device_registered` | `nv002` (không nêu máy) | `LAP-0417` đã đăng ký, `PC-0977` chưa |
| `check_device_registered` | `nv001`, `KHONG-CO` | 404 → rỗng (không phải lỗi) |
| `check_vpn_cert_expiry` | `nv001`, `LAP-0342` | `status=expired`, `days_to_expiry=-3` |
| `check_last_connection` | `nv001` / `nv003` | lần gần nhất `failed`, `CERT_EXPIRED` / `[]` |
| `check_catalog_entry` | `Zoom` / `utorrent` | miễn phí, trong danh mục / 404 → rỗng |
| `check_license_available` | `ms-project` / `adobe-acrobat-pro` | `available=0` / `available=3` |
| `check_installed_list` | `LAP-0342` / `PC-0977` | `ms-office`, `zoom` / `[]` |
| `check_current_permissions` | `nv002`, `finance/Q3` | một quyền `read`, `status=expired` |
| `check_resource_sensitivity` | `finance/Q3` | `sensitivity=high` |
| `check_manager_chain` | `l1_01` / `fin_head` | `[it_mgr01]` / `[]` |

Bật `POST /_admin/faults {"path_prefix": "/vpn", "mode": "error", "status": 500}` → tool VPN trả lỗi hệ
thống sau 3 lần gọi (E2, không phải "không tồn tại"); `DELETE /_admin/faults` → chạy lại bình thường.
