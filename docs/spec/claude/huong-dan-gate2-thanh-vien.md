# Hướng dẫn chạy xác nhận cổng 2 (dành cho Claude Code trên máy thành viên)

> **Người dùng:** mở Claude Code trong một thư mục trống (ví dụ `~/work`), rồi dán:
> *"Đọc file HUONG-DAN-GATE2-THANH-VIEN.md và làm theo từng bước. Dừng lại hỏi tôi khi gặp bước cần tôi làm."*
>
> **Claude Code:** file này là toàn bộ nhiệm vụ của bạn. Làm đúng thứ tự, không bỏ bước. Đọc kỹ mục 0 trước khi chạy bất cứ lệnh nào.

---

## 0. Mục tiêu và luật bắt buộc

**Mục tiêu:** chạy lại bộ kiểm tra `make gate2 S=all` của đồ án AIP_FA26_G8 trên **máy này** (khác máy người code chính), để xác nhận cổng 2: hệ thống chạy đúng trên stack Docker thật, kể cả khi restart, hết hạn, bị SIGKILL giữa lượt. Đồng thời ghi thông tin GPU (`nvidia-smi`).

**Luật bắt buộc — không có ngoại lệ:**

1. **Không sửa code, không sửa test, không sửa Makefile, không sửa `docker-compose.yml`.** Nhiệm vụ là *chạy và báo cáo*, không phải *sửa cho xanh*. Gặp FAIL thì ghi lại nguyên văn và báo, **không** tự sửa.
2. **Không commit, không push, không tạo branch mới.**
3. **Không in giá trị bí mật ra màn hình** (mật khẩu, khóa, token trong `.env`). Khi kiểm `.env` chỉ dùng lệnh `grep` các biến không bí mật ở mục 4.4.
4. **Không bao giờ chạy `docker compose down -v`** hoặc bất cứ lệnh nào xóa volume.
5. Không chạy lệnh `sudo` trừ các lệnh cài đặt ở mục 2 — và phải hỏi người dùng trước.
6. Nếu sandbox của bạn chặn lệnh Docker/mạng: **không nới sandbox**. Đưa lệnh cho người dùng tự chạy (trong Claude Code: gõ `!` ở đầu dòng rồi dán lệnh), đợi họ dán kết quả.
7. Mọi bước "Đạt khi" phải đạt mới sang bước sau. Không đạt → dừng, báo người dùng kèm output.

---

## 1. Nhận diện máy

Chạy và ghi lại kết quả (sẽ đưa vào báo cáo):

```bash
uname -a
cat /etc/os-release 2>/dev/null | head -3
```

| Máy | Cách làm |
|---|---|
| **Windows** | Mọi lệnh chạy **trong WSL 2 (Ubuntu)**, không chạy trong PowerShell/CMD. Nếu Claude Code đang chạy trong PowerShell → dừng, bảo người dùng mở Ubuntu (WSL) và chạy Claude Code từ đó |
| **Linux** | Chạy trực tiếp |
| **macOS** | Chạy trực tiếp; Docker qua Docker Desktop hoặc colima |

**Đạt khi:** xác định được đang ở Linux/WSL/macOS.

---

## 2. Công cụ cần có

Kiểm từng cái:

```bash
git --version
make --version | head -1
docker version
docker compose version
uv --version
python3 --version
```

**Thiếu thì cài** (hỏi người dùng trước khi chạy lệnh `sudo`):

| Thiếu | Cài (Ubuntu/WSL) |
|---|---|
| git, make, curl | `sudo apt update && sudo apt install -y git make curl` |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` rồi `source ~/.bashrc` |
| Docker | **Người dùng tự làm:** cài Docker Desktop (Windows/macOS), bật WSL 2 backend và *Settings → Resources → WSL Integration → bật cho Ubuntu*. Sau đó mở lại cửa sổ Ubuntu |

**Đạt khi:** `docker version` in ra cả **Client** và **Server**, `docker compose version` chạy được, `uv --version` chạy được.

Nếu `docker version` báo `Cannot connect to the Docker daemon` → bảo người dùng mở Docker Desktop, đợi nó chạy xong, rồi thử lại.

**Nhắc người dùng:** tắt chế độ ngủ của máy trong ~1,5 giờ tới (Windows: *Settings → System → Power → Sleep: Never*). Máy ngủ giữa chừng sẽ làm kịch bản FAIL oan.

---

## 3. Lấy code

Người dùng phải có quyền truy cập repo `17tuanphamanh/AIP_FA26_G8` (nếu `git clone` báo 404/403 → dừng, bảo người dùng nhờ Tuấn Anh mời làm collaborator).

```bash
cd ~
git clone https://github.com/17tuanphamanh/AIP_FA26_G8.git
cd AIP_FA26_G8
git checkout dev-tuananh
git pull
git log -1 --oneline
```

**Quan trọng (Windows/WSL):** clone vào thư mục nhà của Ubuntu (`~`), **không** clone vào `/mnt/c/...` — Docker trên ổ Windows chạy rất chậm và dễ lỗi quyền file.

**Đạt khi:** `git log -1` cho commit **`2a9f3ee`** hoặc mới hơn trên nhánh `dev-tuananh`. Ghi lại mã commit vào báo cáo.

Từ đây mọi lệnh chạy ở **gốc repo** (`~/AIP_FA26_G8`).

---

## 4. Tạo file `.env` riêng cho máy này

**Không** xin `.env` của người khác. Mỗi máy tự sinh bí mật ngẫu nhiên.

### 4.1. Tìm cách tạo `.env` có sẵn trong repo

```bash
ls -la .env.example
grep -nE '^[a-z_-]+:' Makefile | head -40
grep -niE 'env' README.md | head -20
```

Nếu Makefile hoặc README có lệnh tạo `.env` (ví dụ `make env`, `make init`, script `scripts/*env*`) → dùng lệnh đó, rồi sang 4.3.

### 4.2. Nếu không có lệnh sẵn: tạo từ `.env.example`

```bash
cp .env.example .env
chmod 600 .env
```

Đọc `.env.example` (file mẫu, không chứa bí mật thật) để biết biến nào là **bí mật** (tên chứa `PASSWORD`, `SECRET`, `KEY`, `TOKEN`, hoặc giá trị mẫu kiểu `changeme`/`xxx`/rỗng). Với mỗi biến bí mật, thay giá trị bằng chuỗi ngẫu nhiên **bằng script, không in ra màn hình**, ví dụ:

```bash
python3 - <<'EOF'
import re, secrets, pathlib
p = pathlib.Path(".env")
lines = p.read_text().splitlines()
out = []
for line in lines:
    m = re.match(r'^([A-Z0-9_]+)=(.*)$', line)
    if m and re.search(r'(PASSWORD|SECRET|KEY|TOKEN)', m.group(1)) and m.group(2).strip() in ("", "changeme", "change-me", "xxx", "CHANGE_ME"):
        line = f"{m.group(1)}={secrets.token_urlsafe(32)}"
    out.append(line)
p.write_text("\n".join(out) + "\n")
print("da sinh bi mat cho cac bien con trong")
EOF
```

Sau đó mở `.env.example` và kiểm **tên biến** (không in giá trị) xem còn biến bí mật nào có định dạng đặc biệt (ví dụ khóa mã hóa MFA cần đúng độ dài/định dạng Fernet/base64). Nếu `.env.example` có ghi chú định dạng → sinh đúng định dạng đó (ví dụ Fernet: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — ghi thẳng vào file bằng script, không in ra). Không chắc → **dừng và hỏi người dùng**, họ sẽ hỏi Tuấn Anh.

### 4.3. Bốn biến bắt buộc cho gate2

Đảm bảo `.env` có **đúng một** dòng cho mỗi biến sau (thêm nếu thiếu, sửa nếu khác):

```
APP_ENV=dev
FAKE_APPROVER_ID=l1_01
FAKE_SCENARIO=approval
FAKE_NODE_DELAY=40
```

### 4.4. Kiểm (lệnh này không in bí mật)

```bash
grep -E '^(APP_ENV|FAKE_APPROVER_ID|FAKE_SCENARIO|FAKE_NODE_DELAY)=' .env
grep -c '=' .env
ls -l .env
```

**Đạt khi:** in ra đúng 4 dòng trên, `.env` có quyền `-rw-------`, và số biến trong `.env` ≥ số biến trong `.env.example`.

**Không bao giờ** `cat .env`.

---

## 5. Dựng stack

```bash
make up
```

Lần đầu có thể mất 5–15 phút (tải image, build). Sau đó:

```bash
docker compose ps
curl -s http://127.0.0.1:8000/api/health
```

**Đạt khi:**
- `postgres`, `qdrant`, `mock`, `backend`, `worker` đều `running`, và `worker` là `(healthy)`.
- `/api/health` trả JSON có `"runtime": "up"`.

**Lỗi thường gặp:**

| Thấy | Nghĩa | Làm |
|---|---|---|
| `APP_ENV phai khai bao trong .env` | Thiếu `APP_ENV` | Quay lại 4.3 |
| Lỗi về socket colima / `DOCKER_HOST` | Makefile nhận nhầm môi trường Mac | **Không sửa Makefile.** Dừng, báo người dùng kèm nguyên văn lỗi |
| backend khởi động lỗi, log nói về biến cấu hình | `.env` thiếu/sai định dạng một biến | `docker compose logs backend --tail 50` (kiểm log không chứa bí mật trước khi đưa người dùng), quay lại 4.2 |
| `runtime: "down"` | Backend không mở được kết nối DB/graph | `docker compose logs backend --tail 80`, báo người dùng |

---

## 6. Chạy kiểm tra cổng 2

### 6.1. Preflight

```bash
make gate2 S=preflight
```

**Đạt khi:** mọi dòng là `PASS`, bảng cuối 0 FAIL.

Nếu ticket preflight dừng ở `S_PENDING_APPROVAL` thay vì `S_CLARIFYING` → `.env` thiếu `FAKE_SCENARIO` hoặc chưa dựng lại stack sau khi sửa `.env`. Sửa `.env` rồi `make down && make up` (**không** `-v`), chạy lại preflight.

### 6.2. Toàn bộ

```bash
make gate2 S=all 2>&1 | tee gate2-all.log
```

- Mất khoảng **30–40 phút**. **Không** Ctrl+C, không đóng cửa sổ, không để máy ngủ.
- Kịch bản `kill` và `kill-b15` có thể **đứng im tới ~6 phút mỗi cái**: đó là lúc chờ worker tự phục hồi lượt bị giết, **không phải treo**.
- Script tự chạy các lệnh `docker compose` (restart, kill, stop, start) và in từng lệnh trước khi chạy — đó là hành vi đúng.

**Đạt khi:** bảng tổng cuối cùng **0 FAIL**.

### 6.3. Bảng threads

```bash
make gate2 S=threads 2>&1 | tee gate2-threads.log
```

**Đạt khi:** mỗi `ticket_id` có `thread_id` trùng với chính nó; số thread = số ticket; không có thread lạ; ticket nào cũng có ≥ 1 checkpoint.

### 6.4. Nếu có FAIL

- **Không sửa code, không chạy lại nhiều lần cho tới khi xanh.**
- Chạy lại **đúng kịch bản đó một lần** (`make gate2 S=<tên kịch bản>`) để xem có lặp lại không.
- Ghi vào báo cáo: tên kịch bản, **nguyên dòng FAIL** (có `ticket_id`), ~20 dòng log phía trên, và kết quả lần chạy lại.
- Với mỗi `ticket_id` bị FAIL, lấy audit (không chứa bí mật):

```bash
echo "SELECT step, event, created_at FROM audit_logs WHERE ticket_id = '<ticket_id>' ORDER BY log_id" \
  | docker compose --env-file .env exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

---

## 7. Thông tin GPU (N2)

```bash
nvidia-smi
```

(Trong WSL, nếu `nvidia-smi` không có → bảo người dùng chạy `nvidia-smi` trong PowerShell và dán kết quả.)

Ghi lại: **tên GPU**, **tổng VRAM** (dòng dạng `xxxxMiB`), phiên bản driver.

---

## 8. Viết báo cáo

Tạo file `~/gate2-ket-qua.md` (**ngoài** thư mục repo để không lẫn vào git), nội dung:

```markdown
# Kết quả gate2 — <tên thành viên> — <ngày giờ>

## Máy
- OS: <uname / os-release>
- Chạy trong: <WSL Ubuntu / Linux / macOS>
- GPU: <tên>, VRAM: <MiB>, driver: <phiên bản>

## Code
- Nhánh: dev-tuananh, commit: <mã 7 ký tự>

## Kết quả
- preflight: <x PASS / y FAIL>
- all: <x PASS / y FAIL>
- threads: <đạt / không đạt> — <số ticket> ticket, <số thread> thread

## Bảng tổng (copy nguyên văn cuối gate2-all.log)
<dán>

## FAIL (nếu có)
<tên kịch bản, dòng FAIL, 20 dòng log trước, kết quả chạy lại, audit của ticket>

## Ghi chú
<lỗi cài đặt gặp phải và cách đã xử lý>
```

Rồi in ra đường dẫn file và **nói với người dùng**: "Gửi file `~/gate2-ket-qua.md` cùng `gate2-all.log` cho Tuấn Anh."

Kiểm lần cuối trước khi báo xong:

```bash
git -C ~/AIP_FA26_G8 status --short     # không được có file code bị sửa (chỉ được có file log/untracked)
grep -iE '(password|secret|token|key)=' ~/gate2-ket-qua.md || echo "khong co bi mat trong bao cao"
```

**Đạt khi:** `git status` không có dòng ` M` (file đã theo dõi bị sửa), và báo cáo không chứa bí mật.

---

## 9. Dọn dẹp (tùy chọn, hỏi người dùng trước)

Stack có thể để chạy hoặc tắt:

```bash
make down        # KHÔNG thêm -v
```

---

## Tóm tắt cho người dùng

| Bước | Ai làm | Thời gian |
|---|---|---|
| Cài Docker Desktop + WSL (nếu chưa có) | Người dùng | 15–30 phút |
| Clone, tạo `.env`, `make up` | Claude Code | 10–20 phút |
| `make gate2 S=all` | Claude Code (người dùng để máy chạy) | 30–40 phút |
| Báo cáo | Claude Code | 5 phút |
| Gửi file cho Tuấn Anh | Người dùng | — |
