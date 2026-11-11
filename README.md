# AIP_FA26_G8 — servicedesk-agent

Repo đồ án môn AIP, kỳ Fall 2026, nhóm 8.
**AI Agent tự động hoá IT Service Desk cấp 1 với Human-in-the-Loop.** Đặc tả đầy đủ ở
[docs/spec/](docs/spec/) — bắt đầu từ [docs/spec/CLAUDE.md](docs/spec/CLAUDE.md).
Tiến độ theo phase ở [PROGRESS.md](PROGRESS.md).

**Chạy lại hệ thống từ đầu (hội đồng, người ngoài nhóm):** xem [docs/HUONG-DAN-CHAY.md](docs/HUONG-DAN-CHAY.md).

## Bản nộp và bản đo

| Mốc | Ở đâu | Dùng cho |
| --- | --- | --- |
| **Bản đo** | tag `v1.0-freeze` (`bf94df2`, 29/10/2026) | Mọi số liệu RQ trong báo cáo đo trên bản này. Muốn chạy lại số liệu: `git checkout v1.0-freeze`. |
| **Bản nộp** | nhánh `main` (14/11/2026) | Mã nguồn nộp và video demo. Gồm bản đo + mọi thay đổi sau đó (sửa lỗi sau buổi test của giám khảo, các lô Q1–Q13). Phần khác bản đo ghi ở báo cáo mục "Bản nộp khác bản đo" và [PROGRESS.md](PROGRESS.md). |

Hệ thống: LangGraph B1→B20 (sàng lọc → phân loại → chẩn đoán → trả lời KB hoặc thực thi có duyệt → kiểm chứng → audit),
FastAPI + PostgreSQL + Qdrant + ml-service (embed, rerank, phân loại) + mock AD/VPN/phần mềm/file server, giao diện React.
Quyết định thiết kế đánh số D-xx ở [docs/spec/build/decisions.md](docs/spec/build/decisions.md).

### Cờ tính năng của bản nộp (`.env`, mặc định đều bật)

Mỗi tính năng thêm sau bản đo có một cờ; đặt `false` là quay về đúng hành vi cũ, không cần đổi code.

| Cờ | Quyết định | Tắt thì |
| --- | --- | --- |
| `ENABLE_IT_HELP` | D-76 — câu hỏi IT chung (máy in, Wi-Fi, Outlook…) trả lời từ KB `general` | coi như ngoài phạm vi (E1) |
| `ENABLE_KB_FOLLOWUP` | D-78 — "Chưa ổn" + ghi chú sau câu trả lời KB → hỏi tiếp tối đa 2 vòng trong cùng ticket | E8 như bản đo |
| `ENABLE_SESSION_MEMORY` | D-79 — "Hỏi tiếp về yêu cầu này" trên ticket đã kết thúc → ticket mới mang gợi ý loại việc trước | không có ô hỏi tiếp |
| `ENABLE_QUERY_REWRITE` | D-80 — câu hỏi gõ không dấu / viết tắt / có lời chào mà điểm truy hồi dưới ngưỡng → viết lại câu, truy hồi lại một lần (cùng ngưỡng) | chuyển kỹ thuật viên (E3) như bản đo |

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

**`.env` phải có `LLM_BACKEND`:** `scripted` (LLM giả `ScriptedLLM`, không gọi API — máy dev, test, cổng) hoặc `real` (LLM thật theo
`config/llm.yaml`, cách bật ở [docs/HUONG-DAN-CHAY.md](docs/HUONG-DAN-CHAY.md) mục 9). Thiếu thì `make up`/`make gate2` dừng và
backend/worker từ chối khởi động.

### Đổi hàm băm khoá ticket (G1)

Khoá ticket là `pg_advisory_lock(hashtextextended(ticket_id, 0))` (bigint, 64 bit; trước là `hashtext`, 32 bit nên hai ticket khác nhau
có thể trùng khoá và chặn nhau). Đổi hàm băm là đổi khoá: dừng và khởi động lại `backend` VÀ `worker` cùng lúc, đừng để bản cũ và bản
mới chạy song song (khoá của hai bản không còn loại trừ nhau, và lượt đang giữ khoá kiểu cũ không bị chặn bởi bản mới).

Lệnh khác: `make ingest` (nạp KB), `make seed` (đặt lại dữ liệu mock), `make eval-rag` (đo truy hồi trên KB đang chạy),
`make probe F=<bộ câu>` (LLM thật, tốn tiền), `make gate2…gate5` (cổng từng phase). `make eval` và `make load` vẫn in TODO
và thoát mã 1 (chưa nối vào Makefile). Script đo offline nằm ở `scripts/eval/`; chuẩn bị môi trường đo: hướng dẫn chạy mục 11.

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
