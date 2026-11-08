# E2E tối thiểu (Playwright): `npm run e2e`

Chạy giao diện thật (`npm run dev`, **không** phải `dev:mock`) với backend thật ở `127.0.0.1:8000`.
Phạm vi theo hợp đồng thông báo, mục 3:

| Tệp | Kiểm |
|---|---|
| `dang-nhap-quan-ly.e2e.ts` | quản lý `quan.tm` (mật khẩu + OTP do test tự sinh) vào `/dashboard`, thanh bên đúng: Tổng quan, Cảnh báo, Chính sách, Trạng thái LLM, Chờ tôi duyệt |
| `dang-nhap.e2e.ts` | nhân viên `an.nv` → `/chat` (Yêu cầu mới) · L1 `ha.lt` → `/approvals` (Chờ tôi duyệt, Hàng đợi escalate) · L2 `long.nh` → `/escalations` (Hàng đợi escalate). Các mục khác của thanh bên phải vắng. |
| `l1-chinh-sach.e2e.ts` | `ha.lt` gọi `GET /api/policy` bằng chính phiên trình duyệt → **403**. Thanh bên không có "Chính sách". Mở thẳng `/policy` → "Bạn không có quyền xem trang này", và giao diện không gọi API chính sách. |
| `chat-dien-thoai.e2e.ts` | **Khổ điện thoại 390×844** (cảm ứng): `an.nv` đăng nhập, thanh bên thu vào nút Menu (mở/đóng bằng nút, Esc, "Đóng menu", chạm liên kết), bảng thông báo nằm trọn trong màn, ô chat + nút gửi trong màn. Đo bố cục thật: không cuộn ngang cả trang, nút / ô nhập cao ≥ 44 px, chữ ≥ 14 px. **Không gửi tin** (gửi = tạo ticket thật). Bàn phím ảo của máy thật không giả lập được → kiểm bằng điện thoại thật. Chạy riêng: `npm run e2e -- chat-dien-thoai`. |

**Mật khẩu và bí mật TOTP lấy từ anh Tuấn Anh (gửi riêng).** Chỉ đặt chúng bằng biến môi trường trong phiên terminal
(PowerShell, hoặc Git Bash dùng `read -rs` / `export`). **Không** lưu vào tệp nào trong repo, **không** đưa vào
`.env`, không dán vào chat hay PR. Thiếu biến thì test của vai đó **bỏ qua** (không đỏ), và lý do được in ở cuối lượt
chạy.

**OTP của quản lý:** test tự sinh mã TOTP (RFC 6238: SHA-1, 6 số, bước 30 giây; `e2e/totp.ts`, chỉ dùng
`node:crypto`) từ secret base32 đã enroll MFA của `quan.tm`. Backend **không** có cờ bỏ MFA, và e2e không thêm cờ nào.
Mỗi lượt gửi **tối đa 2 mã, thường chỉ 1**:
- Nếu cửa sổ 30 giây hiện tại còn dưới 5 giây, test chờ sang cửa sổ mới rồi mới sinh mã.
- Mã đầu bị từ chối thì test **dừng ngay**. Ngoại lệ duy nhất: mã rơi sát ranh giới cửa sổ (lúc gửi còn ≤ 3 giây,
  hoặc lúc nhận phản hồi đồng hồ đã sang cửa sổ sau). Khi đó test chờ sang cửa sổ mới, sinh lại mã từ giờ hiện tại
  và gửi lần 2.
- Lần 2 sai thì dừng.

**Bị từ chối thì KHÔNG chạy lại liên tục, hãy báo anh Tuấn Anh.** OTP sai cộng dồn có thể bắn cảnh báo an ninh, và
backend khoá `quan.tm` sau 5 lần sai trong 10 phút.

| Biến | Dùng cho |
|---|---|
| `E2E_PASSWORD` | mật khẩu chung. Tài khoản demo trong seed dùng chung một mật khẩu (`mock_services/README.md`, mục "Dữ liệu demo"). |
| `E2E_PASSWORD_AN`, `E2E_PASSWORD_HA`, `E2E_PASSWORD_LONG`, `E2E_PASSWORD_QUAN` | mật khẩu riêng từng vai (nếu đặt, dùng thay `E2E_PASSWORD`) |
| `E2E_MANAGER_TOTP_SECRET` | bí mật TOTP (base32) đã enroll MFA của `quan.tm`. Anh Tuấn Anh gửi riêng, không qua chat hay PR. |
| `E2E_BASE_URL` | địa chỉ giao diện (mặc định `http://localhost:5173`) |
| `E2E_CHROMIUM_PATH` | đường dẫn tới tệp chạy Chrome/Chromium có sẵn trên máy (không đặt thì Playwright tự tìm) |

## Windows (PowerShell): hướng dẫn cho Quân

1. **Node** theo `engines` trong `frontend/package.json`: `^22.22.0 || ^24.0.0 || >=26.0.0`. Kiểm bằng `node -v`.
2. **Cài thư viện** (npm 11, trong thư mục `frontend`):
   ```powershell
   cd frontend
   npx -y npm@11 ci
   ```
3. **Trình duyệt.** Chọn một trong hai cách:
   - Dùng Chrome đã cài sẵn trên máy (không tải gì):
     `$env:E2E_CHROMIUM_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"`
   - Hoặc tải Chromium của Playwright một lần: `npx playwright install chromium`
4. **Backend** phải đang chạy ở `127.0.0.1:8000`, đã nạp seed demo, và `quan.tm` đã đăng ký MFA. Kiểm nhanh:
   `curl.exe http://127.0.0.1:8000/api/health` phải trả 200.
5. **Đặt mật khẩu** (anh Tuấn Anh gửi riêng) cho phiên PowerShell này. Biến chỉ sống trong cửa sổ hiện tại, không
   lưu vào tệp nào. Không tạo `.env`, không ghi vào tệp trong repo. Nên dùng
   `Read-Host` để mật khẩu **không** vào lịch sử lệnh (PSReadLine ghi mọi dòng gõ `$env:...="..."` vào tệp lịch sử):
   ```powershell
   $env:E2E_PASSWORD = Read-Host "Mat khau demo"          # PowerShell 7 thêm -MaskInput để không hiện ký tự
   # hoặc từng vai: $env:E2E_PASSWORD_HA = Read-Host "Mat khau ha.lt"   (tương tự _AN, _LONG, _QUAN)
   ```
6. **Đồng bộ giờ máy** trước khi chạy, vì mã TOTP phụ thuộc giờ máy. Vào Settings → Time & language → Date & time,
   bật "Set time automatically" rồi bấm "Sync now". Nếu có quyền admin thì dùng `w32tm /resync` cũng được. Sau đó
   **đặt bí mật TOTP** của `quan.tm` (anh Tuấn Anh gửi riêng), cũng bằng `Read-Host`:
   ```powershell
   $env:E2E_MANAGER_TOTP_SECRET = Read-Host "TOTP secret quan.tm"
   ```
7. **Chạy cả bộ:**
   ```powershell
   npm run e2e
   ```
   Chỉ chạy riêng test quản lý: `npm run e2e -- -g "quản lý"`. Nếu chưa đặt secret, test quản lý được ghi là bỏ qua
   và các test khác vẫn chạy. Test quản lý đỏ vì "OTP bị từ chối" thì **không** chạy lại liên tục: báo anh Tuấn Anh.
8. **Xong thì xoá biến** (hoặc đóng cửa sổ): `Remove-Item Env:E2E_PASSWORD*, Env:E2E_MANAGER_TOTP_SECRET`.

Kiểm riêng hàm TOTP (không cần backend hay trình duyệt). Lệnh này dùng vector chuẩn RFC 6238, ví dụ T=59 cho mã
`287082`: `node --test e2e/totp.test.ts`. Node 22.18 trở lên tự bỏ kiểu TypeScript; Node cũ hơn thì thêm
`--experimental-strip-types`.

## Git Bash (Windows) / macOS / Linux (bản ngắn)

```bash
cd frontend && npx -y npm@11 ci
# trình duyệt: npx playwright install chromium   (hoặc export E2E_CHROMIUM_PATH=/đường/dẫn/chrome)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/health   # phải là 200
read -rs -p "Mat khau demo: " E2E_PASSWORD && export E2E_PASSWORD && echo
read -rs -p "TOTP secret quan.tm: " E2E_MANAGER_TOTP_SECRET && export E2E_MANAGER_TOTP_SECRET && echo
npm run e2e                     # giờ máy phải đồng bộ (Windows: Sync now / w32tm /resync; macOS/Linux: NTP)
node --test e2e/totp.test.ts    # kiểm riêng hàm TOTP bằng vector RFC 6238
unset E2E_PASSWORD E2E_MANAGER_TOTP_SECRET
```

## Đọc kết quả

- Mỗi dòng có một dấu ở đầu: `✓` là đạt, `✘` là đỏ, `-` là bỏ qua. Cuối lượt chạy có dòng tổng (`N passed`,
  `N failed`, `N skipped`), và mục **"BỎ QUA n test"** cho biết từng test bị bỏ qua vì thiếu biến nào.
  Lệnh trả mã thoát khác 0 khi có test đỏ.
- Test đỏ thì thông báo lỗi nói rõ điều kiện sai. Ví dụ:
  `GET /api/policy bằng phiên L1 phải bị backend từ chối 403 — Expected: 403, Received: 200`.
- Tệp kèm theo nằm ở `frontend/.verify/e2e/` (đã gitignore). Gồm ảnh `test-failed-1.png` khi đỏ và
  `error-context.md`. Test quản lý **không** chụp ảnh vì ô OTP hiện chữ số; mã sinh ra không bao giờ được in.
  Ô mật khẩu là `type=password` nên không lộ trong ảnh.
- Không có trace, video hay báo cáo HTML (các thứ đó có thể ghi lại giá trị đã gõ). `retries = 0`: test đỏ không
  tự chạy lại, nên không làm tăng số lần đăng nhập sai.

## Lỗi thường gặp

| Triệu chứng | Nguyên nhân, cách xử lý |
|---|---|
| `GET /api/health qua dev server ≠ 200` | Backend chưa chạy ở `127.0.0.1:8000`, hoặc cổng 5173 đang bị một chương trình khác chiếm. |
| `trang có service worker — dev server đang chạy npm run dev:mock` | Cổng 5173 đang chạy bản mock (MSW). Tắt nó đi. Playwright sẽ tự bật `npm run dev` thật. |
| `Executable doesn't exist at ...ms-playwright...` | Chưa có Chromium của Playwright. Làm bước 3: đặt `E2E_CHROMIUM_PATH` hoặc chạy `npx playwright install chromium`. |
| `Port 5173 is already in use` (dev server không bật) | Một chương trình khác giữ cổng 5173. Tắt nó, hoặc chạy giao diện ở chỗ khác rồi đặt `E2E_BASE_URL`. |
| `không vào được (POST /api/auth/login → 401)` | Sai mật khẩu, hoặc tài khoản đang bị khoá (5 lần sai trong 10 phút). Kiểm lại biến, chờ hết khoá. **Đừng** chạy lặp liên tục. |
| `quan.tm: không sang bước OTP (... cần 401 mfa_required)` | `quan.tm` chưa đăng ký MFA trên backend này (đăng ký bằng CLI `app.auth.mfa`), hoặc sai mật khẩu. |
| `OTP bị từ chối — kiểm E2E_MANAGER_TOTP_SECRET và giờ máy (đồng bộ thời gian)` | Giờ máy lệch (đồng bộ lại theo bước 6), hoặc bí mật không phải cái đang enroll. **Không chạy lại liên tục**, báo anh Tuấn Anh. Mỗi lượt đã tính 1 (tối đa 2) lần OTP sai. |
| `secret TOTP không phải base32` / `secret TOTP rỗng` | Dán nhầm secret. Secret base32 chỉ gồm chữ A–Z và số 2–7; dấu cách, gạch nối và `=` được bỏ qua. |
| Test L1/chính sách đỏ ở bước 403 | Backend đang cho L1 đọc chính sách: đây là **lỗi phân quyền thật**. Báo nhóm backend kèm dòng lỗi. |
