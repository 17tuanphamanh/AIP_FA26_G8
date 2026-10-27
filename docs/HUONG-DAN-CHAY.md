# Hướng dẫn chạy hệ thống — AI Agent IT Service Desk L1

> Viết theo nhánh `dev-tuananh` @ `1a0145f` (26/10/2026). Đã chạy thử từ đầu trên commit này (lựa chọn A — chưa có 2 model nhóm, LLM giả): xoá sạch → `make up` → `make ingest` → web (`npm ci`) → đăng nhập các vai → đặt OTP `quan.tm` → `make up RATE=loose`. Chỗ đánh dấu ⚠️ **CẦN BỔ SUNG** là phần đang chờ nhóm cung cấp; ❗ là lời dặn quan trọng cho người chạy.
> Sơ đồ kiến trúc: [`docs/kien-truc/kien-truc-gon.svg`](kien-truc/kien-truc-gon.svg) (gọn) · [`docs/kien-truc/kien-truc-8-tang.svg`](kien-truc/kien-truc-8-tang.svg) (đầy đủ).

**File này dành cho ai:** người **ngoài nhóm** cần dựng và chạy lại hệ thống từ đầu (hội đồng chấm, người chạy lại kết quả). Không cần biết trước gì về dự án — cứ làm đúng thứ tự, chép **nguyên văn** từng lệnh.

## Mục lục

1. [Yêu cầu máy](#1-yêu-cầu-máy) — Windows: [chuẩn bị WSL2](#11-chuẩn-bị-trên-windows-wsl2)
2. [Lấy mã nguồn và quyền truy cập repo](#2-lấy-mã-nguồn-và-quyền-truy-cập-repo)
3. [Tạo file `.env`](#3-tạo-file-env)
4. [Lấy model](#4-lấy-model)
5. [Dựng hệ thống](#5-dựng-hệ-thống)
6. [Bật giao diện web](#6-bật-giao-diện-web)
7. [Tài khoản demo](#7-tài-khoản-demo)
8. [Đặt OTP cho tài khoản quản lý `quan.tm`](#8-đặt-otp-cho-tài-khoản-quản-lý-quantm)
9. [Bật LLM thật](#9-bật-llm-thật)
10. [Dừng, dọn dẹp, chạy lại từ đầu](#10-dừng-dọn-dẹp-chạy-lại-từ-đầu)
11. [Chạy đánh giá (G8)](#11-chạy-đánh-giá-g8) — ghi giờ, nới giới hạn, chuyển cache LLM giữa hai máy
12. [Lỗi thường gặp](#12-lỗi-thường-gặp)
13. [Lệnh khác](#13-lệnh-khác)

---

## 0. Đọc trước khi bắt đầu

- Mọi lệnh chạy **trong terminal, tại thư mục gốc của repo** (thư mục có file `Makefile`), trừ khi ghi khác.
- **Windows:** chạy trong terminal **WSL2 (Ubuntu)** — **không** dùng PowerShell, CMD hay **Git Bash** (trừ vài lệnh ghi rõ là PowerShell). Cách chuẩn bị WSL2: mục 1.1.
- Lệnh trong khung ```` ```bash ```` chép nguyên văn, chạy lần lượt từng lệnh. Chỗ nào phải tự điền sẽ ghi rõ.
- Mặc định hệ thống dùng **LLM giả** (`scripted`) — **không tốn tiền**. Chỉ tốn tiền khi bạn tự bật LLM thật (mục 9).
- **Ghi lại giờ lúc chạy** khi chạy đánh giá (mục 11.1): một số ca cho kết quả khác nhau tuỳ chạy trong hay ngoài giờ hành chính.

---

## 1. Yêu cầu máy

| Thứ cần có | Ghi chú |
|---|---|
| Docker + Docker Compose **v2 trở lên** | `make up` dùng `docker compose up --wait` (Compose v1 `docker-compose` không chạy được). Windows: Docker Desktop dùng WSL2. macOS: Docker Desktop hoặc colima (Makefile tự nhận socket colima). Kiểm: `docker compose version` |
| `make`, `git`, `curl`, `python3` | Kiểm: `make --version`, `git --version`, `curl --version`, `python3 --version` |
| `uv` | **Cài trên máy**, không chỉ trong container: `make up` chạy `uv run` để kiểm model trước khi build. Kiểm: `uv --version` |
| Node.js + npm | Cho giao diện web. Node phải là **22.22 trở lên trong dòng 22, hoặc 24.x, hoặc ≥ 26** (theo `engines` trong `frontend/package.json`). Kiểm: `node --version`, `npm --version` |
| Mạng tới `huggingface.co` | Chỉ lần đầu, để `make models` tải model (~4–5 GB). |
| Ổ đĩa trống ≥ ~10 GB | Model ~4–5 GB + image Docker (+ 2 model của nhóm nếu dùng). |

**RAM:**

- **Không nạp 2 model của nhóm** (lựa chọn A, mục 4.2): đo trên máy nhóm (WSL2 được cấp 7,6 GiB), stack đã dựng xong, để yên với LLM giả — tổng các container ~**1,8 GiB**: `ml-service` ~1,06 GiB, `backend` ~280 MiB, `worker` ~260 MiB, `qdrant` ~115 MiB, `postgres` ~65 MiB, `mock` ~50 MiB (chưa tính giao diện web và trình duyệt).
- **Nạp model intent của nhóm** (lựa chọn B): `ml-service` dùng thêm **~1,2 GB RAM**. Tổng các container phải ≤ 7 GB và không bị hệ thống "giết" vì thiếu RAM (OOMKilled). **Máy 8 GB thì không nạp model intent** (để trống các biến `INTENT_*`).
- Khuyến nghị: máy **8 GB RAM** cho lựa chọn A, cấp cho Docker/WSL **ít nhất 4 GB**; máy **16 GB** nếu nạp đủ 2 model. Thiếu RAM: xem mục 12.

### 1.1. Chuẩn bị trên Windows (WSL2)

Trên Windows, mọi lệnh `make`, `docker compose`, `npm` trong file này chạy **bên trong Ubuntu của WSL2** — đây là cách máy nhóm đang chạy. **Không** cài `make` cho Git Bash (ezwinports, choco…): `make up` dùng lệnh shell kiểu Linux, và `make ingest` gắn thư mục bằng đường dẫn tuyệt đối — chạy từ Git Bash dễ hỏng giữa chừng. Trong WSL không cần chỉnh gì Makefile.

1. Mở **PowerShell với quyền quản trị**, cài Ubuntu cho WSL2 (đã có thì bỏ qua), rồi khởi động lại máy và đặt tên người dùng/mật khẩu Ubuntu khi được hỏi:

   ```powershell
   wsl --install -d Ubuntu
   ```

2. **Docker Desktop** → Settings → Resources → **WSL integration** → bật cho **Ubuntu** → Apply & restart.

3. Mở terminal **Ubuntu**, cài công cụ:

   ```bash
   sudo apt update && sudo apt install -y make git curl python3
   ```

4. Cài `uv`, rồi **đóng và mở lại** terminal Ubuntu:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

5. Cài Node.js 24 (bản Node trong `apt` của Ubuntu thường quá cũ):

   ```bash
   curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash - && sudo apt install -y nodejs
   ```

6. Kiểm đủ công cụ (mục 1, cột "Kiểm"): `docker compose version`, `make --version`, `uv --version`, `node --version`.

7. Clone repo **bên trong Ubuntu**, ở thư mục nhà (`cd ~`), theo mục 2.2.
   - **Không** dùng bản repo đã clone bằng Git for Windows / Git Bash, và **không** đặt repo trong `/mnt/c/...`: Git for Windows có thể đổi ký tự xuống dòng (CRLF) làm hỏng script, còn thư mục `/mnt/c` chạy chậm hơn nhiều trong WSL.
   - File cần chép từ Windows (ví dụ 2 model nhóm) thì chép từ `/mnt/c/...` hoặc `/mnt/<ổ>/...` vào repo trong Ubuntu.

---

## 2. Lấy mã nguồn và quyền truy cập repo

### 2.1. Quyền truy cập (hội đồng)

Repo là repo riêng tư trên GitHub: `https://github.com/17tuanphamanh/AIP_FA26_G8`.

- **Cách chính:** nhóm thêm tài khoản GitHub của thầy/cô làm **collaborator**. Sau khi chấp nhận lời mời (qua email hoặc trang thông báo GitHub), clone theo mục 2.2.
- **Dự phòng:** tải **file zip của tag `v1.0-freeze`** (trang *Tags* của repo, hoặc file zip nhóm gửi kèm), giải nén rồi làm tiếp từ mục 3 bên trong thư mục giải nén.

Bản dùng để chạy và chấm là tag **`v1.0-freeze`** (nhóm tạo tag chiều 27/10, chậm nhất sáng 28/10).

### 2.2. Clone

```bash
git clone https://github.com/17tuanphamanh/AIP_FA26_G8
```

```bash
cd AIP_FA26_G8
```

Chuyển sang đúng bản dùng để chạy — tag `v1.0-freeze`:

```bash
git checkout v1.0-freeze
```

- Git sẽ báo `You are in 'detached HEAD' state` — **bình thường** khi đứng trên tag. Chỉ chạy, **không commit gì** trên tag.
- Báo `pathspec 'v1.0-freeze' did not match`: tag chưa được tạo hoặc bản clone chưa có tag — chạy `git fetch --tags` rồi thử lại. Trước khi có tag (trước 28/10), người chạy thử trong nhóm dùng `git checkout dev-tuananh`.

---

## 3. Tạo file `.env`

```bash
cp .env.example .env
```

Mở `.env` để kiểm (ví dụ bằng `nano .env`; lưu: `Ctrl+O` → `Enter`, thoát: `Ctrl+X`):

- `LLM_BACKEND=scripted` — **bắt buộc có**. `scripted` là LLM giả, không tốn tiền (dùng cho lần dựng đầu). Bật LLM thật: mục 9.
- `ML_SERVICE_TOKEN` — **bắt buộc có giá trị**, thiếu thì compose dừng ngay.
- `FAKE_NODE_DELAY` — **để trống** (còn giá trị thì worker không lên).
- `TICKET_RATE_10MIN`, `TICKET_RATE_HOUR`, `MESSAGE_RATE_10MIN` (giới hạn chống spam) — **để trống** = dùng mặc định. Khi cần nới (chạy đánh giá), dùng `make up RATE=loose` (mục 11.2), không sửa ở đây.
- Các dòng model của nhóm (`GUARD_*`, `INTENT_*`) và `B2_CLASSIFIER_MODE`, `B2_TAU_REVIEW` — **giữ nguyên như `.env.example`** (đang là dòng chú thích `#`), trừ khi làm theo lựa chọn B ở mục 4.2.
- Các khoá/mật khẩu khác (`JWT_SIGNING_KEY`, `MFA_ENC_KEY`, `SVC_*_TOKEN`, `PG_*`…) giữ giá trị mẫu là chạy được.

> ❗ **Không commit `.env`**, không đưa khoá thật vào repo, PR hay tin nhắn.
> Không có `.env` thì Makefile dùng tạm `.env.example` và in cảnh báo — không nên chạy như vậy.

---

## 4. Lấy model

Hệ thống dùng **hai loại model**, nằm ở **hai thư mục khác nhau** — đừng nhầm:

| Thư mục | Chứa gì | Lấy bằng cách nào | Bắt buộc? |
|---|---|---|---|
| `models/` | Model chung của ml-service (embed, rerank) | `make models` (tự tải từ huggingface.co) | **Có** — thiếu thì `make up` dừng |
| `ml_models/` | **2 model của nhóm**: phân loại injection (`injection-clf`) và phân loại intent (`intent-clf`) | Tải riêng (mục 4.2) — **không có trong repo** (nằm trong `.gitignore`) | Không — chạy được khi chưa có (lựa chọn A) |

### 4.1. Model chung — `make models` (chỉ lần đầu)

```bash
make models
```

- Tải ~4–5 GB vào `./models`, đúng revision ghim trong `ml_service/models.lock.json`. Có thể mất nhiều phút tuỳ mạng.
- Đổi thư mục: `make models up MODELS_DIR=/duong/dan` (đây là **biến của make**, không đặt trong `.env`).
- Thiếu model thì `make up` dừng với thông báo `Thiếu model cho ml-service — chạy: make models`.

### 4.2. 2 model của nhóm — chọn A hoặc B

#### Lựa chọn A — chạy khi chưa có 2 model của nhóm (mặc định)

- Không làm gì thêm: để thư mục `ml_models/` trống, các dòng `GUARD_*`, `INTENT_*` trong `.env` giữ nguyên như `.env.example`.
- Hệ thống vẫn dựng và chạy bình thường. Các lời gọi chấm điểm của model nhóm trả **503** (chưa nạp model); bước sàng lọc injection (B2) và phân loại intent (B3) dùng **LLM**.
- Đây là cấu hình nhóm đã chạy thử thật (dựng, đăng nhập đủ các vai, đặt OTP).

#### Lựa chọn B — nạp 2 model của nhóm

1. Tải 2 thư mục model:

   ⚠️ **CẦN BỔ SUNG:** link Drive 2 model của nhóm (`<link Drive>`) và cách giải nén (nếu là file nén).

2. Đặt vào thư mục `ml_models/` ở gốc repo, giữ nguyên cấu trúc. Theo cấu hình mẫu, model intent dùng bản safetensors `ml_models/intent-clf/v3.1-seed42-st` (thư mục gốc có `seed_42.pt` **không** nạp được — ml-service từ chối khởi động).

3. Kiểm mỗi thư mục model **đủ và đúng từng file** bằng file `MANIFEST.sha256` có sẵn trong thư mục:

   ```bash
   for m in $(find ml_models -name MANIFEST.sha256 | sort); do d=$(dirname "$m"); echo "== $d"; (cd "$d" && sha256sum -c --quiet MANIFEST.sha256 && [ "$(find . -type f ! -name MANIFEST.sha256 | wc -l)" -eq "$(wc -l < MANIFEST.sha256)" ] && echo "tat ca file OK, khong thua khong thieu" && sha256sum MANIFEST.sha256 model.safetensors || echo "LOI: file sai, thieu hoac thua so voi MANIFEST"); done
   ```

   - Mỗi thư mục phải in `tat ca file OK, khong thua khong thieu`. File sai/thiếu sẽ in `FAILED`; có file **thừa** (không nằm trong manifest) hoặc thiếu sẽ in `LOI: …` — **tải lại / xoá file thừa**, vì sai, thiếu hay thừa file đều làm ml-service từ chối khởi động.
   - Hai dòng SHA in ra cuối mỗi thư mục (của `MANIFEST.sha256` và `model.safetensors`) phải **trùng** với giá trị đặt trong `.env` ở bước 4.

4. Đặt 6 dòng sau vào `.env` (đường dẫn là đường dẫn **trong container**: `/ml_models/...` ứng với `./ml_models/...` trên máy). Các mã SHA-256 **không phải bí mật**:

   ```dotenv
   GUARD_MODEL_DIR=/ml_models/injection-clf/<phiên bản>
   GUARD_MODEL_SHA256=<sha256 của model.safetensors>
   GUARD_MANIFEST_SHA256=<sha256 của MANIFEST.sha256>
   INTENT_MODEL_DIR=/ml_models/intent-clf/v3.1-seed42-st
   INTENT_MODEL_SHA256=<sha256 của model.safetensors>
   INTENT_MANIFEST_SHA256=<sha256 của MANIFEST.sha256>
   ```

   ⚠️ **CẦN BỔ SUNG:** 6 dòng giá trị chính xác (nhóm cung cấp cùng link Drive).

   - Đặt `GUARD_MODEL_DIR` thì **bắt buộc** đủ `GUARD_MODEL_SHA256` và `GUARD_MANIFEST_SHA256`; tương tự với `INTENT_*`. Thiếu hoặc lệch → **ml-service từ chối khởi động và cả stack đứng** (backend chờ ml-service).
   - Máy 8 GB: chỉ đặt 3 dòng `GUARD_*`, để trống 3 dòng `INTENT_*` (mục 1, RAM).

5. Dựng lại: `make up` (mục 5.1). Lần đầu nạp model nhóm, ml-service khởi động lâu hơn (kiểm SHA-256 + nạp, thêm ~10–25 s cho model intent).

---

## 5. Dựng hệ thống

### 5.1. Dựng stack

```bash
make up
```

`make up` tự làm lần lượt:

1. Kiểm model chung của ml-service đã có (`models/`).
2. Build image `backend`, `mock`, `ml-service`.
3. Bật `postgres`, `qdrant`, chờ sẵn sàng.
4. Chạy migration DB (`alembic upgrade head`).
5. Bật `ml-service`, `backend`, `worker`, `mock` — backend và worker **chờ ml-service healthy** (đang làm nóng, xem mục 5.6).
6. Chờ mock `/health` OK, rồi **tự nạp dữ liệu demo** (`make seed`).
7. Chờ worker `healthy`, rồi chờ `/api/health` OK và in kết quả.

Mỗi bước chờ có giới hạn thời gian; quá hạn thì in log của service lỗi và dừng (xem mục 12).

⏱ **Lần đầu mất khá lâu** (build image + ml-service làm nóng, cho phép tới 4 phút). Đứng lâu ở bước ml-service là bình thường, **không phải treo**. Tham khảo: trên máy nhóm (WSL2), khi đã có model, cả `make up` mất khoảng **4 phút** (phần lớn là build image).

**Chạy thành công thì cuối output có các dòng như sau:**

```text
mock /health: ok
seed hợp lệ: .../mock_services/seed.json — 17 người dùng, 10 thiết bị
mock đã nạp lại seed: {'status': 'reset', 'users': 17, 'devices': 10}
worker: healthy
/api/health: {"status":"ok","checks":{"db":"ok","qdrant":"ok","mock":"ok","ml":"ok"},"failed":[],"runtime":"up", ...}
```

### 5.2. Nạp lại dữ liệu demo — `make seed`

`make up` đã tự chạy bước này. Chạy lại khi muốn đưa dữ liệu mock về **ban đầu** (đồng thời tắt mọi lỗi đang bơm vào mock, xoá hộp thư SMS/email giả):

```bash
make seed
```

Cần `make up` đang chạy.

### 5.3. Nạp kho kiến thức (KB)

```bash
make ingest
```

- Cần `make up` chạy xong trước.
- ⏱ Mất khoảng **10–15 phút** (đo trên máy nhóm: ~12 phút, trong đó tạo embedding chỉ ~40 giây; phần còn lại là build image, cổng kiểm KB và tạo snapshot). Đứng im lâu là bình thường.
- Kết quả in `kb_version` và số đoạn bị cắt (truncated) — **số này phải bằng 0**.
- Chạy thử không ghi: `make ingest ARGS=--dry-run`.

**Chạy thành công thì cuối output có các dòng như sau:**

```text
tài liệu: 18 enabled / 18 tổng; số đoạn: 77; max text_tokens: 277; truncated=0
...
alias kb_current → kb_<kb_version>
...
xong: kb_version=..., collection=kb_..., số đoạn=77, truncated=0, eval_status=evaluated
```

- Trên DB vừa xoá sạch có thể gặp dòng `cảnh báo: owner it_mgr01 chưa có trong bảng users — ghi kb_documents.owner = NULL`. Ingest vẫn hoàn tất bình thường.
- Ngay sau khi ingest xong, `/api/health` có thể vẫn báo `kb.status = missing` thêm **khoảng 10–60 giây** (backend kiểm lại KB theo chu kỳ ~10 giây) — chờ rồi kiểm lại (mục 5.4), **không cần** khởi động lại gì.

### 5.4. Kiểm nhanh

```bash
docker compose ps
```

Mọi service ở trạng thái `running` / `healthy`.

```bash
curl -s http://127.0.0.1:8000/api/health | python3 -c "import sys, json; print(json.load(sys.stdin).get('runtime'))"
```

Phải in ra `up`.

- `/api/health` **luôn trả 200**; trạng thái thật nằm ở trường `runtime`.
- Các trường khác: `checks` (từng thành phần lõi, phải đều `ok`), `failed` (thành phần lỗi, phải rỗng `[]`), `kb.status` (`missing` khi chưa nạp KB — ví dụ ngay sau khi xoá sạch; `ready` sau khi `make ingest`), `llm` (`scripted` = đang dùng LLM giả), `monitor`.
- `runtime` chỉ tính phần lõi: DB, Qdrant, mock, ml-service. Các trường `kb`, `llm`, `monitor` chỉ để tham khảo.
- Container backend có healthcheck riêng: healthy khi `/api/health` trả 200 **và** `runtime == "up"` (chờ khởi động 60 s).

### 5.5. Cổng và service

| Service | Truy cập từ máy? | Ghi chú |
|---|---|---|
| Giao diện web | ✅ `http://localhost:5173` | Không thuộc compose — bật bằng `npm run dev` (mục 6) |
| `backend` | ✅ `http://127.0.0.1:8000` | Cổng duy nhất của compose mở ra máy (chỉ localhost) |
| `worker` | ❌ | |
| `mock` | ❌ (cổng 8100 trong mạng compose) | Gọi tay: xem `mock_services/README.md` mục "Chạy" |
| `ml-service` | ❌ (cổng 8200 trong mạng compose) | |
| `postgres` | ❌ | Dữ liệu ở volume `pgdata` |
| `qdrant` | ❌ | KB ở volume `qdrant` |

### 5.6. Làm nóng

- **Làm nóng chạy tự động bên trong container `ml-service`** mỗi khi container khởi động: nạp model chung, kiểm SHA-256 và nạp model của nhóm (nếu có). Không cần lệnh riêng.
- Healthcheck ml-service chỉ báo `healthy` khi đã nạp + làm nóng xong (kiểm mỗi 10 s, cho phép khởi động tới **240 s**). Backend và worker chờ ml-service healthy rồi mới lên.
- **Đổi cấu hình ml-service** (thư mục model, `ML_THREADS`, `GUARD_*`, `INTENT_*`, …) → chạy lại `make up` để build lại và làm nóng với cấu hình mới.

**Trước buổi demo**, chạy sớm (ít nhất ~5 phút trước):

```bash
make up
```

```bash
make ingest
```

rồi bật giao diện web trong một terminal khác (mục 6).

---

## 6. Bật giao diện web

Giao diện web **không** được `make up` bật — phải chạy riêng từ thư mục `frontend/`. Web gọi backend qua proxy (`/api` → `http://127.0.0.1:8000`), nên **`make up` phải chạy xong trước**.

1. Mở **một terminal mới** (giữ nguyên terminal cũ), vào thư mục gốc repo, rồi:

   ```bash
   cd frontend
   ```

2. Cài thư viện (lần đầu, hoặc khi `package-lock.json` đổi) — `npm ci` cài **đúng** bản đã khoá trong `package-lock.json` và **không tự sửa** file lock:

   ```bash
   npm ci
   ```

   Chỉ khi `npm ci` báo lỗi `package-lock.json` không khớp với `package.json` thì mới dùng `npm install` thay thế.

   Cuối output có thể báo `vulnerabilities` và gợi ý `npm audit fix`, hoặc gợi ý nâng npm — **bỏ qua, không chạy các lệnh đó** (chúng sửa `package-lock.json` / đổi phiên bản, khiến bạn chạy bộ thư viện khác với bộ nhóm đã khoá).

3. Bật web:

   ```bash
   npm run dev
   ```

   Thành công khi in `VITE … ready` và `Local: http://localhost:5173/`; terminal **đứng yên** ở đó là đúng.

4. Mở trình duyệt vào **http://localhost:5173** và đăng nhập (mục 7).

- **Giữ terminal này mở** trong suốt lúc dùng web. Tắt web: bấm `Ctrl+C` trong terminal đó.
- Mở đúng địa chỉ `http://localhost:5173` — không mở thẳng cổng 8000 trên trình duyệt (đăng nhập dùng cookie cùng origin qua proxy).

> ❗ **Dùng `npm run dev`, KHÔNG dùng `npm run dev:mock`** (hay `VITE_API_MOCK=1 npm run dev`). Bản `dev:mock` trộn **dữ liệu minh hoạ** vào giao diện (có nhãn "Dữ liệu minh hoạ" ở góc màn hình) — kết quả sẽ không phải của hệ thống thật. Thấy nhãn đó thì tắt (`Ctrl+C`) và chạy lại `npm run dev`.

> Lưu ý: thao tác trên web là **ghi thật** vào hệ thống (ví dụ ghi đè quyết định ticket, đánh dấu cảnh báo "Đã xem") và không hoàn tác được. Muốn làm lại từ đầu: mục 10.

---

## 7. Tài khoản demo

### 7.1. Đăng nhập

- Đăng nhập ở giao diện web **http://localhost:5173**.
- **Mật khẩu chung cho mọi tài khoản: `Demo@2026!`** — mật khẩu công khai, chỉ dùng cho môi trường demo (nguồn: `mock_services/README.md`, mục "Dữ liệu demo").
- Dữ liệu demo được nạp tự động khi `make up`; nạp lại về ban đầu: `make seed`.
- Trang đăng nhập ghi "Dùng tài khoản công ty (AD) của bạn" — nhập **tên đăng nhập** ở cột "Tài khoản" bảng dưới (ví dụ `an.nv`), không nhập mã.
- Sau khi vào, góc dưới bên trái hiện **mã người dùng + vai trò** (ví dụ `nv001` · Nhân viên) — dùng để kiểm mình đang ở đúng tài khoản. Đăng xuất: biểu tượng mũi tên ngay bên phải dòng đó.

> ❗ **Không đăng nhập `quan.tm` trước khi đặt OTP** (mục 8): mỗi lần đăng nhập khi chưa có OTP bị tính là 1 lần sai (`mfa_not_enrolled`), lặp lại sẽ **tự khoá tài khoản**.

### 7.2. Vai trò và menu

| Vai trò | Menu bên trái |
|---|---|
| Nhân viên | Yêu cầu mới, Gần đây |
| IT Helpdesk L1 (người duyệt) | Chờ tôi duyệt, Hàng đợi escalate |
| Kỹ thuật viên L2 | Hàng đợi escalate |
| Trưởng bộ phận IT (manager) | Tổng quan, Cảnh báo, Chính sách, Chờ tôi duyệt |

Mọi vai trò đều có ô chat ở giữa màn hình ("Hôm nay IT giúp gì cho bạn?").

### 7.3. Danh sách tài khoản (17 người trong seed)

| Tài khoản | Họ tên | Mã hiện trên web | Vai trò | Ghi chú |
|---|---|---|---|---|
| `quan.tm` | Trần Minh Quân | `it_mgr01` | Trưởng bộ phận IT | **Cần OTP** — đặt trước theo mục 8 |
| `khoa.dv` | Đặng Văn Khoa | `l1_lead` | IT Helpdesk L1 | |
| `ha.lt` | Lê Thu Hà | `l1_01` | IT Helpdesk L1 | |
| `duc.pv` | Phạm Văn Đức | `l1_02` | IT Helpdesk L1 | |
| `long.nh` | Nguyễn Hoàng Long | `l2_01` | Kỹ thuật viên L2 | |
| `an.nv` | Nguyễn Văn An | `nv001` | Nhân viên | Có `LAP-0342`, chứng chỉ hết hạn 3 ngày |
| `binh.tt` | Trần Thị Bình | `nv002` | Nhân viên | `LAP-0417` đã đăng ký, `PC-0977` chưa đăng ký |
| `chau.hm` | Hoàng Minh Châu | `nv003` | Nhân viên | Đang thử việc |
| `dung.dv` | Đặng Văn Dũng | `nv004` | Nhân viên | **Bị vô hiệu hoá** — không đăng nhập được |
| `hoa.bt` | Bùi Thị Hoa | `nv005` | Nhân viên | Người nhận bàn giao khi xử lý `dung.dv` |
| `em.lv` | Lý Văn Em | `nv006` | Nhân viên | **Đã nghỉ việc** — không đăng nhập được |
| `giang.pt` | Phan Thu Giang | `nv007` | Nhân viên | |
| `lan.dt` | Đỗ Thị Lan | `fin_head` | Nhân viên | Trưởng phòng Kế toán |
| `cuong.vq` | Vũ Quốc Cường | `eng_head` | Nhân viên | Trưởng phòng Kỹ thuật |
| `son.nt` | Ngô Thanh Sơn | `sales_head` | Nhân viên | Trưởng phòng Kinh doanh |
| `mai.tt` | Trịnh Thị Mai | `hr_head` | Nhân viên | Trưởng phòng Nhân sự |
| `svc-backup` | Tài khoản dịch vụ sao lưu | `svc_backup` | — | **Không dùng để đăng nhập** |

### 7.4. Dữ liệu dựng sẵn — cố ý, không phải lỗi

Các điểm dưới đây có thể trông lạ khi chạy lại, nhưng đều là **dữ liệu demo được dựng sẵn có chủ đích**:

- `khoa.dv`: chức danh trong dữ liệu là **"Trưởng nhóm Helpdesk"**, nhưng vai trò trên web là **IT Helpdesk L1** (menu giống `ha.lt`).
- `quan.tm`: menu có **Tổng quan, Cảnh báo, Chính sách, Chờ tôi duyệt**.
- 4 trưởng phòng (`lan.dt`, `cuong.vq`, `son.nt`, `mai.tt`) đăng nhập với vai trò **Nhân viên** — không có quyền gì thêm trên web.
- `dung.dv` (bị vô hiệu hoá) và `em.lv` (đã nghỉ việc) **không đăng nhập được** — bị từ chối với câu **"Tên đăng nhập hoặc mật khẩu không đúng."** Hệ thống cố ý báo chung chung (không tiết lộ tài khoản bị vô hiệu hoá), **không phải gõ sai mật khẩu**. **Đừng thử lại nhiều lần.**
- `svc-backup`: tài khoản dịch vụ, **không dùng để đăng nhập**.
- Mốc thời gian trong seed là **tương đối**: "chứng chỉ hết hạn 3 ngày trước" luôn đúng dù chạy ngày nào.

---

## 8. Đặt OTP cho tài khoản quản lý `quan.tm`

Làm **một lần**, sau khi `make up` chạy xong (và làm lại sau mỗi lần xoá sạch DB — mục 10).

Lệnh dưới đã chạy thử thành công trên `dev-tuananh` @ `1a0145f` ngày 26/10/2026, trên DB vừa xoá sạch.

1. Chạy lệnh dưới, **thay `ten-cua-ban` bằng tên người chạy** (viết liền, không dấu):

   ```bash
   docker compose exec backend python -m app.auth.mfa enroll quan.tm --by ten-cua-ban --reason demo
   ```

2. Lệnh in ra mã `otpauth://…`. Thêm vào app **Google Authenticator** trên điện thoại: bấm **"+"** → **"Quét mã QR"**; hoặc **"Nhập khoá thiết lập"** — tên tài khoản `quan.tm`, khoá là phần chữ sau `secret=` (tới dấu `&` kế tiếp), loại **Dựa trên thời gian**.
3. Ở giao diện web, nhập `quan.tm` / `Demo@2026!` → bấm **Đăng nhập**.
4. Web chuyển sang **trang riêng "Nhập mã xác thực"** ("Mã 6 số trong ứng dụng xác thực trên điện thoại") với 6 ô. Nhập mã 6 số đang hiện trong app → bấm **Xác nhận**. (Nút **Quay lại** để về trang đăng nhập.)
   - Mã đổi mỗi 30 giây — nếu vòng đếm sắp hết thì chờ mã mới rồi nhập.
   - Báo sai mã thì chỉ thử lại **1 lần** với mã mới; sai nhiều lần có thể làm tài khoản bị khoá.
5. Vào được thì góc dưới trái hiện `it_mgr01` · Trưởng bộ phận IT.

- ❗ **Mã `otpauth` là bí mật** — không chụp màn hình gửi đi, không dán vào tin nhắn hay báo cáo.
- **Đã đặt rồi nhưng mất app:** chạy lại lệnh trên với `reset` thay cho `enroll`. Lưu ý: `reset` **đăng xuất mọi phiên cũ** của `quan.tm`.

   ```bash
   docker compose exec backend python -m app.auth.mfa reset quan.tm --by ten-cua-ban --reason demo
   ```

**Nếu `quan.tm` đã bị khoá** (đăng nhập khi chưa đặt OTP, hoặc nhập sai OTP nhiều lần):

- Cách chắc chắn gỡ được là **xoá sạch rồi dựng lại** (mục 10): `docker compose down -v` → `make up` → `make ingest` → đặt lại OTP theo các bước 1–5 ở trên. Mất khoảng 15 phút. Cách này đưa DB của backend và dữ liệu mock về ban đầu, nên trạng thái khoá cũng mất theo.
- ❗ Xoá sạch sẽ mất **toàn bộ** ticket, lịch sử và cache trong DB — kể cả cache LLM của lượt đánh giá. Nếu đang chạy đánh giá, **xuất cache trước** (mục 11.3, lệnh 1). Chỉ dùng cách này khi không còn cách khác.
- Nếu nhóm có lệnh mở khoá nhanh hơn sẽ bổ sung tại đây.

---

## 9. Bật LLM thật

Mặc định dùng LLM giả (`LLM_BACKEND=scripted`, giá 0). Dùng LLM thật **không cần sửa code**, chỉ cần các bước dưới.

### 9.1. Đặt biến trong `.env`

Ba biến `LLM_BASE_URL`, `FAST_MODEL`, `STRONG_MODEL` **không có sẵn trong `.env.example`** — phải tự thêm dòng. Mở `.env` (`nano .env`), sửa dòng `LLM_BACKEND`, rồi thêm các dòng còn lại cho đủ như sau (nhóm dùng DeepSeek, cả hai vai trò đều là `deepseek-flash`):

```dotenv
LLM_BACKEND=real
LLM_BASE_URL=https://api.deepseek.com
FAST_MODEL=deepseek-flash
STRONG_MODEL=deepseek-flash
LLM_API_KEY=dien-key-cua-ban-vao-day
```

Thay `dien-key-cua-ban-vao-day` bằng API key DeepSeek của bạn. Sau khi lưu `.env`, chạy lại:

```bash
make up
```

### 9.2. Model phải có dòng giá

- `config/llm.yaml` có bảng `pricing` (USD / 1 triệu token, in/out). Hiện có sẵn: `scripted`, `deepseek-flash`, `deepseek-v4-pro` — **dùng DeepSeek như mục 9.1 thì không cần sửa gì**.
- Model **không có dòng giá thì không bao giờ được gọi**; đặt `LLM_BACKEND=real` mà `FAST_MODEL`/`STRONG_MODEL` không có dòng giá → **hệ thống từ chối khởi động**.
- Dùng nhà cung cấp/model khác: thêm dòng giá của model đó vào `pricing` trước.
- Giá DeepSeek trong bảng là **giá giờ cao điểm** (giờ thấp điểm bằng một nửa) → số tiền hệ thống đếm luôn dư, an toàn.
- DeepSeek mặc định bật chế độ suy nghĩ; hệ thống đã tự tắt qua trường `thinking` trong request — không cần làm gì thêm.

### 9.3. Trần chi phí

- `config/llm.yaml`: `spend.cap_usd = 38` (USD), cảnh báo khi dùng tới 80% (`warn_ratio: 0.8`), cập nhật số tiêu mỗi 60 s.
- Nên đặt thêm **hạn mức ngay trên key** ở trang nhà cung cấp, phòng khi hệ thống đếm sai.
- Khi `.env` đang `LLM_BACKEND=real`, chạy demo và chạy đánh giá đều **tốn tiền**.

### 9.4. Quay về LLM giả

Sửa trong `.env`:

```dotenv
LLM_BACKEND=scripted
```

rồi chạy:

```bash
make up
```

---

## 10. Dừng, dọn dẹp, chạy lại từ đầu

| Muốn | Lệnh | Dữ liệu |
|---|---|---|
| Dừng | `make down` | **Giữ** DB và KB (kể cả OTP đã đặt) |
| Xoá sạch và dựng lại | `docker compose down -v` → `make up` → `make ingest` | **Xoá** DB và KB (volume `pgdata`, `qdrant`) — phải `make ingest` lại |
| Đưa dữ liệu mock về ban đầu | `make seed` | Chỉ mock; tắt mọi lỗi đang bơm, xoá hộp thư SMS/email giả |

> `docker compose down -v` cần `.env` có `LLM_BACKEND` và `ML_SERVICE_TOKEN` (compose đọc biến cả khi dừng).
> Xoá sạch DB thì phải **đặt lại OTP** cho `quan.tm` (mục 8).

---

## 11. Chạy đánh giá (G8)

### 11.1. Ghi giờ lúc chạy

Một số ca cho kết quả **khác nhau tuỳ chạy trong hay ngoài giờ hành chính**. Mỗi lần chạy đánh giá, ghi lại giờ bắt đầu (kèm múi giờ) cùng kết quả:

```bash
date '+%Y-%m-%d %H:%M:%S %Z'
```

### 11.2. Nới giới hạn chống spam

Hệ thống giới hạn số ticket và tin nhắn mỗi tài khoản trong một khoảng thời gian (vượt → lỗi **429**). Giới hạn **không tắt được**, chỉ **nới** bằng số rất lớn. Chạy đánh giá (gửi nhiều yêu cầu liên tiếp) cần nới trước:

```bash
make up RATE=loose
```

Chạy đánh giá xong, đưa về mặc định (dựng lại stack, không kèm `RATE`):

```bash
make up
```

- `RATE` chỉ nhận đúng giá trị `loose` (hoặc bỏ trống); giá trị khác → `make` dừng ngay, chưa đụng tới container nào, với lỗi:

  ```text
  Makefile:36: *** RATE=sai không hợp lệ — chỉ RATE=loose (nới ngưỡng 429) hoặc bỏ trống.  Stop.
  ```

- Kiểm giới hạn đang nới hay mặc định:

  ```bash
  docker compose exec -T backend sh -c 'echo "T10=[$TICKET_RATE_10MIN] TH=[$TICKET_RATE_HOUR] M10=[$MESSAGE_RATE_10MIN]"'
  ```

  Sau `make up RATE=loose`: cả 3 là `100000`. Sau `make up` (mặc định): cả 3 rỗng `[]`.
- **Ghi vào biên bản** mỗi lần chạy có nới giới hạn.

### 11.3. Chuyển cache LLM của lượt đánh giá giữa hai máy (G8)

Ba lệnh dưới **xuất** các dòng cache LLM chế độ đánh giá (bảng `llm_cache`, `mode = 'eval'`) ở **máy nguồn** ra file CSV, rồi **nạp** vào **máy đích**, để máy đích dùng lại cache của lượt đánh giá đã chạy. Lệnh dùng biến có sẵn trong container postgres — không chứa tên người dùng hay tên DB, không cần sửa gì.

**Điều kiện trước khi chạy:**

- Hai máy phải **cùng tag `v1.0-freeze`** để các cột của bảng khớp nhau.
- Stack đang chạy (`make up`) ở máy tương ứng.
- **Windows:** chạy trong **WSL** như các mục khác (riêng 3 lệnh này chạy bằng **Git Bash** cũng được) — **PowerShell** không hiểu dấu `<` ở lệnh nạp (2).

**1. Xuất cache eval ra file CSV (máy nguồn):**

```bash
docker compose --env-file .env exec -T postgres sh -c 'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "COPY (SELECT * FROM llm_cache WHERE mode = '\''eval'\'') TO STDOUT WITH (FORMAT csv, HEADER)"' > ~/llm_cache_eval.csv; echo exit=$?
```

Phải in `exit=0`. File nằm ở `~/llm_cache_eval.csv`.

**Chuyển file sang máy đích** (USB, Drive…) — ❗ **không commit file CSV** vào repo. Kiểm mã băm ở **hai đầu**, hai mã phải **trùng nhau**:

```bash
sha256sum ~/llm_cache_eval.csv
```

(macOS dùng `shasum -a 256 ~/llm_cache_eval.csv`.)

**2. Nạp vào máy đích** (bảng chưa có dòng eval trùng `cache_key`):

```bash
docker compose --env-file .env exec -T postgres sh -c 'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "COPY llm_cache FROM STDIN WITH (FORMAT csv, HEADER)"' < ~/llm_cache_eval.csv; echo exit=$?
```

Phải in `exit=0`.

> ❗ Nếu lệnh 2 báo **trùng khoá** (duplicate key) nghĩa là máy đích **đã có cache** này. Khi đó **dừng lại và hỏi nhóm** — **không tự xoá** dữ liệu trong bảng.

**3. Kiểm số dòng theo mode (chạy ở cả hai máy):**

```bash
docker compose --env-file .env exec -T postgres sh -c 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT mode, count(*) FROM llm_cache GROUP BY mode ORDER BY mode"'
```

Số dòng `eval` ở máy đích sau khi nạp phải bằng số dòng `eval` ở máy nguồn (máy đích chưa có dòng `eval` nào trước khi nạp). Tham khảo: lần thử của nhóm xuất **28 dòng** eval, nạp đủ 28 dòng.

---

## 12. Lỗi thường gặp

### 12.1. Docker thiếu RAM

| Triệu chứng | Cách xử lý |
|---|---|
| `make up` dừng ở bước ml-service; ml-service khởi động lại liên tục; máy rất chậm | Kiểm ml-service có bị giết vì thiếu RAM: `docker inspect -f '{{.State.OOMKilled}}' $(docker compose ps -aq ml-service)` — in `true` là thiếu RAM. Xem RAM đang dùng: `docker stats --no-stream` |

Cách tăng RAM cho Docker:

- **Windows (Docker Desktop dùng WSL2):** tạo/sửa file `C:\Users\<tên-bạn>\.wslconfig`:

  ```ini
  [wsl2]
  memory=6GB
  ```

  rồi mở **PowerShell** chạy `wsl --shutdown`, mở lại Docker Desktop và terminal WSL.
- **macOS / Docker Desktop:** Settings → Resources → Memory.
- Không tăng được: bỏ model intent của nhóm (để trống 3 dòng `INTENT_*` trong `.env`, bớt ~1,2 GB), hoặc dùng lựa chọn A (mục 4.2), rồi `make up`.

### 12.2. ml-service chưa nạp model / không lên

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `Thiếu model cho ml-service — chạy: make models` | Chưa tải model chung / sai `MODELS_DIR` | `make models` (cùng `MODELS_DIR` với lúc `make up`) — mục 4.1 |
| Đứng lâu ở bước ml-service (tới ~4 phút) | Đang nạp + làm nóng — **bình thường** | Chờ; quá 240 s mới là lỗi |
| `ml-service/backend/worker không lên` kèm 50 dòng log ml-service | Model của nhóm đặt sai: thiếu biến SHA, SHA/manifest lệch, thư mục không nằm dưới `/ml_models`, trỏ nhầm thư mục `.pt` thay vì safetensors | Đọc log: `docker compose logs --tail 50 ml-service`. Kiểm lại theo mục 4.2 (bước 3–4). Cần chạy ngay thì quay về lựa chọn A (để các dòng `GUARD_*`, `INTENT_*` như `.env.example`) rồi `make up` |
| `/api/health` trả 200 nhưng `runtime` khác `up`, `checks.ml` khác `ok` | ml-service chưa sẵn sàng | `docker compose ps`, xem log như trên |

### 12.3. Cổng bị chiếm

| Triệu chứng | Cách xử lý |
|---|---|
| `make up` báo `port is already allocated` / `address already in use` (cổng **8000**) | Có chương trình khác (hoặc stack cũ) đang giữ cổng. Tìm trong WSL: `ss -ltnp \| grep ':8000'`; trên Windows (PowerShell): `netstat -ano \| findstr :8000`. Tắt chương trình đó (stack cũ: `make down`), rồi `make up` lại |
| `npm run dev` báo cổng **5173** đang dùng, hoặc chạy sang cổng khác | Còn một terminal web cũ đang chạy. Tìm: `ss -ltnp \| grep ':5173'`; tắt terminal đó (`Ctrl+C`), chạy lại `npm run dev`. Luôn mở đúng địa chỉ dòng `Local:` Vite in ra |

### 12.4. Các lỗi khác

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `ML_SERVICE_TOKEN phai khai bao trong .env` hoặc `LLM_BACKEND phai khai bao trong .env` | `.env` thiếu biến bắt buộc | Thêm biến vào `.env` (mục 3) |
| `CẢNH BÁO: không có .env` | Chưa tạo `.env` | `cp .env.example .env` (mục 3) |
| `docker compose` không có, hoặc báo không nhận cờ `--wait` | Docker Compose quá cũ (v1) | Cài Docker Compose v2 trở lên (mục 1) |
| `make: command not found` | Chưa cài `make`, hoặc đang chạy trong Git Bash / PowerShell | Windows: chạy trong Ubuntu (WSL2) và `sudo apt install -y make` (mục 1.1) — không cài `make` cho Git Bash |
| Trong Ubuntu (WSL) báo `docker: command not found` | Docker Desktop chưa bật WSL integration cho Ubuntu | Docker Desktop → Settings → Resources → WSL integration → bật Ubuntu (mục 1.1) |
| Lỗi lạ kiểu `$'\r': command not found` | Repo clone bằng Git for Windows, xuống dòng kiểu CRLF | Clone lại repo bên trong Ubuntu (mục 1.1 bước 7) |
| `worker chưa healthy sau 60 giây` | `FAKE_NODE_DELAY` trong `.env` còn giá trị | Để trống `FAKE_NODE_DELAY`, `make up` lại |
| `/api/health` báo `kb.status = missing` | Chưa `make ingest` (hoặc vừa xoá sạch), hoặc ingest vừa xong chưa tới ~1 phút | `make ingest` (mục 5.3); vừa ingest xong thì chờ ~1 phút rồi kiểm lại |
| Backend/worker từ chối khởi động sau khi sửa dòng `B2_*` | Đặt `B2_CLASSIFIER_MODE` mà thiếu giá trị đi kèm | Để `B2_CLASSIFIER_MODE`, `B2_TAU_REVIEW` như `.env.example` (mục 3), `make up` lại |
| `make` báo `RATE=... không hợp lệ` | Gõ sai giá trị `RATE` | Chỉ dùng `make up RATE=loose` hoặc `make up` (mục 11.2) |
| Gửi nhiều yêu cầu liên tiếp bị từ chối (429) | Giới hạn chống spam | `make up RATE=loose` (mục 11.2) |
| Kết quả một số ca khác lần chạy trước | Chạy trong / ngoài giờ hành chính | Ghi giờ lúc chạy (mục 11.1) |
| Lệnh nạp cache (11.3 lệnh 2) báo trùng khoá (duplicate key) | Máy đích đã có cache eval này | **Dừng lại, hỏi nhóm** — không tự xoá dữ liệu |
| Lệnh nạp cache báo lỗi cột / kiểu dữ liệu | Hai máy không cùng tag `v1.0-freeze` | Đưa cả hai máy về cùng tag, chạy lại từ lệnh 1 |
| PowerShell báo lỗi ở dấu `<` (lệnh nạp cache) | PowerShell không hỗ trợ chuyển file vào lệnh kiểu này | Chạy bằng WSL hoặc Git Bash (mục 11.3) |
| Mã băm file CSV ở hai máy khác nhau | File hỏng / chép thiếu khi chuyển | Chuyển lại file, kiểm lại mã băm trước khi nạp |
| Bật LLM thật thì hệ thống không khởi động | Model chưa có dòng trong `pricing` / sai tên model | Kiểm `FAST_MODEL`, `STRONG_MODEL` khớp tên trong `config/llm.yaml` (mục 9.2) |
| Mock trả lỗi lạ | Lỗi bơm vào mock vẫn còn bật | `make seed` |
| Tài khoản demo không đăng nhập được bằng `Demo@2026!` (dù không phải `dung.dv`, `em.lv`) | Mật khẩu đã bị đặt lại qua kênh SMS của mock (gọi thẳng API mock) | `make seed` — đưa mọi tài khoản về mật khẩu demo |
| `quan.tm` bị khoá | Đăng nhập khi chưa đặt OTP, hoặc sai OTP nhiều lần | Đặt OTP trước (mục 8); cách mở khoá: xem mục 8 |
| Mất app OTP của `quan.tm` | | Dùng `reset` (mục 8) |
| Web không mở được `localhost:5173` | Chưa chạy `npm run dev`, hoặc đã tắt terminal chạy web | Mục 6 |
| Web mở được nhưng đăng nhập / tải dữ liệu báo lỗi | Backend chưa chạy hoặc chưa sẵn sàng | `make up`, kiểm `/api/health` (mục 5.4) |
| Góc màn hình có nhãn "Dữ liệu minh hoạ" | Đang chạy `npm run dev:mock` | `Ctrl+C`, chạy lại `npm run dev` |
| `npm` báo phiên bản Node không hợp | Node quá cũ | Cài Node 24.x (mục 1) |
| `npm ci` báo lock không khớp | `package-lock.json` lệch `package.json` | Dùng `npm install` (mục 6) |

> Ghi chú: sửa file đang được git theo dõi mà chưa commit rồi `make up` thì image backend không gắn commit (`lineage.commit_sha` rỗng) — không phải lỗi.

---

## 13. Lệnh khác

| Lệnh | Làm gì |
|---|---|
| `make test` | Unit + integration + e2e với LLM giả (không tốn tiền) |
| `make lint` | ruff, mypy, import-linter, gitleaks (cần cài `gitleaks`) |
| `make seed` | Nạp lại dữ liệu demo cho mock |
| `make down` | Dừng stack, giữ dữ liệu |
