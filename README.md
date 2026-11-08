# AIP_FA26_G8 — servicedesk-agent

Repo đồ án môn AIP, kỳ Fall 2026, nhóm 8.
**AI Agent tự động hoá IT Service Desk cấp 1 với Human-in-the-Loop.** Đặc tả đầy đủ ở
[docs/spec/](docs/spec/) — bắt đầu từ [docs/spec/CLAUDE.md](docs/spec/CLAUDE.md).
Tiến độ theo phase ở [PROGRESS.md](PROGRESS.md).

> Hiện mới có **khung thư mục**, chưa có logic nghiệp vụ. Agent thử nghiệm cũ đã gỡ;
> xem lại trong lịch sử git (nhánh `doi-ten-tieng-anh`).

## Dựng môi trường

```bash
# 1. Cài uv (https://docs.astral.sh/uv/), rồi dựng .venv Python 3.12 theo uv.lock
uv sync                      # thêm --group ml nếu cần model nặng của ml-service

# 2. Bật hook dùng chung của repo (làm MỘT LẦN cho mỗi bản clone)
git config core.hooksPath .githooks

# 3. Docker (make up, test integration dùng testcontainers) — trên macOS dùng colima
colima start --cpu 4 --memory 8
docker run --rm hello-world   # kiểm Docker chạy được

# 4. gitleaks (make lint quét bí mật; thiếu thì make lint báo lỗi, không bỏ qua)
brew install gitleaks

# 5. Chạy test và lint
make test
make lint
```

**Makefile tự nhận colima:** nếu có `~/.colima/default/docker.sock` thì các lệnh `make` tự đặt
`DOCKER_HOST` trỏ vào socket đó và `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`
(cho Ryuk của testcontainers) — không cần sửa `~/.zshrc`. Không có socket colima (Docker Desktop,
Linux) thì Makefile để nguyên. Máy từng cài Docker Desktop thường có `"credsStore": "desktop"`
trong `~/.docker/config.json`; Makefile tự thêm `/Applications/Docker.app/Contents/Resources/bin`
vào `PATH` để `docker pull` không lỗi `docker-credential-desktop not found`. Chạy `docker` trực
tiếp ngoài `make` thì tự thêm thư mục đó vào `PATH`.

`make up` dựng compose (postgres, qdrant, backend, worker, mock), chạy migration bằng role
`app_migrate`, rồi chờ `/api/health` trả 200. `make down` dừng container (giữ volume). Chưa có
`.env` thì `make up` dùng `.env.example` và in cảnh báo. Postgres bind `127.0.0.1:55432` (đổi bằng
`PG_PORT`) để khỏi đụng Postgres của dự án khác trên máy.

**Từ Phase 3d, `.env` phải có `LLM_BACKEND=scripted`** (máy dev, LLM giả `ScriptedLLM`, không gọi API) — thiếu thì
`make up`/`make gate2` dừng và backend/worker từ chối khởi động; `real` chỉ dùng từ mốc G (`config/llm.yaml`).

### Đổi hàm băm khoá ticket (G1)

Khoá ticket là `pg_advisory_lock(hashtextextended(ticket_id, 0))` (bigint, 64 bit; trước là `hashtext`, 32 bit nên hai ticket khác nhau
có thể trùng khoá và chặn nhau). Đổi hàm băm là đổi khoá: dừng và khởi động lại `backend` VÀ `worker` cùng lúc, đừng để bản cũ và bản
mới chạy song song (khoá của hai bản không còn loại trừ nhau, và lượt đang giữ khoá kiểu cũ không bị chặn bởi bản mới).

Các lệnh `make ingest | seed | probe | eval | eval-rag | load` đã có tên nhưng chưa có nội dung
(in TODO và thoát mã 1) — sẽ làm theo từng phase.

## Cấu trúc thư mục

Theo [docs/spec/build/01-kien-truc-project.md](docs/spec/build/01-kien-truc-project.md) mục 3.

| Đường dẫn | Chứa gì |
| --- | --- |
| `backend/app/` | Backend modular monolith (FastAPI + LangGraph): `core`, `domain`, `db`, `auth`, `guard`, `llm`, `rag`, `tools`, `risk`, `approval`, `executor`, `audit`, `notify`, `graph`, `monitor`, `eval`, `api` |
| `backend/tests/` | `unit/`, `integration/`, `e2e/` (chạy trong `make test`); `probe/` (LLM thật), `load/` (locust); `fakes/` |
| `ml_service/` | Service model: embed, rerank, phân loại (P4) |
| `ml_models/` | Model phân loại đã xuất (ONNX + ngưỡng + model card) — file `.onnx` không commit |
| `training/` | Script huấn luyện model phân loại (P11); `training/data/`, `training/runs/` không commit |
| `mock_services/` | Giả lập AD, VPN, phần mềm, file server (P5) |
| `frontend/` | React + Vite + TS (P10) |
| `config/` | `policy.json`, `llm.yaml`, patterns, `prompts/` — sửa là đổi hành vi agent |
| `kb/` | Tài liệu KB — được commit |
| `eval/` | Kịch bản, nhãn, kết quả thực nghiệm — được commit |
| `docs/spec/` | Bộ đặc tả |
| `docs/` | Đề bài, kiến trúc (trỏ sang đặc tả), nhật ký nhóm |
| `pyproject.toml`, `uv.lock` | Phụ thuộc Python, pin bằng uv |
| `Makefile` | Lệnh chung (01 mục 7.1) |
| `.githooks/` | Hook git dùng chung — chặn commit khi test đỏ, chặn dấu vết AI |
| `notebooks/` | Notebook thử nghiệm |

## Quy ước làm việc chung

- **Không commit `.env`, dữ liệu nặng, `.venv/`** — đã chặn sẵn trong `.gitignore`. Nếu lỡ commit key thì phải vào trang nhà cung cấp **thu hồi (revoke) key ngay**, xoá dòng code là không đủ.
- Message commit ghi rõ làm được gì, tiếng Việt không dấu — ví dụ `them tool tim kiem tai lieu, test pass`. Tránh `update`, `fix bug`.
- Trước khi commit: `git status` → `git diff` → `make test` → mới `git add -A`.
- Hook ở `.githooks/` sẽ tự chặn nếu test đỏ hoặc message có dấu vết AI — nhưng chỉ
  khi đã chạy `git config core.hooksPath .githooks` ở bước 2. Chưa chạy thì không ai gác.
- Mỗi người làm xong phần của mình thì `git pull` trước, rồi mới `git push`.
