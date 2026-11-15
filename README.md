# AITHA — AI Agent tự động hoá IT Service Desk cấp 1 có Human-in-the-Loop

*Agentic AI for Level-1 IT Service Desk Automation with Human-in-the-Loop* — đồ án tốt nghiệp ngành Trí tuệ nhân tạo,
Đại học FPT, nhóm AIP491_G8, kỳ Fall 2026.

Nhân viên gửi yêu cầu IT bằng tiếng Việt (VPN, tài khoản, phần mềm, quyền truy cập). Agent tự hiểu yêu cầu, tự kiểm tra
trạng thái hệ thống, trả lời từ tài liệu nội bộ có trích nguồn, hoặc thực hiện hành động. Mọi hành động nhạy cảm đều qua
luật cứng hoặc người duyệt, và mọi quyết định đều truy vết được. Đóng góp chính của đồ án là **cơ chế quyết định khi nào
cần chuyển cho con người**.

![Kiến trúc hệ thống](docs/kien-truc/kien-truc-gon.png)

## Điểm chính

- **Luồng agent 20 bước** trên LangGraph: xác thực → sàng lọc tấn công → hiểu và tách yêu cầu → chẩn đoán chủ động →
  trả lời có trích nguồn hoặc đánh giá rủi ro → duyệt → thực thi → xác nhận → ghi nhật ký. Lỗi ở bất kỳ bước nào cũng
  chuyển người, không để treo.
- **Quyết định khi nào cần người:** lớp luật (23 luật, luật chặt nhất thắng) chạy trước và không bị LLM ghi đè; ca luật
  không phủ mới sang lớp LLM ước lượng rủi ro. Khi chưa có bộ hiệu chỉnh đủ tin cậy, lớp LLM chỉ được chuyển lên người,
  không bao giờ tự làm.
- **Duyệt và thực thi an toàn:** phiếu duyệt gắn mã băm của đúng một hành động, OTP cho trưởng bộ phận, kiểm lại luật
  ngay trước khi thực thi, nhật ký giao dịch chỉ ghi thêm, hoàn tác được.
- **Chặn prompt injection nhiều lớp:** mẫu cứng + model phân loại nhóm tự fine-tune + LLM chấm; che mật khẩu, khoá và
  dữ liệu cá nhân trước khi gửi LLM.
- **RAG lai:** bge-m3 (dense) + BM25, rerank bằng bge-reranker-v2-m3; không đủ căn cứ thì chuyển người, không trả lời bừa.
- **Chất lượng:** hơn 11.400 test backend (unit, tích hợp PostgreSQL thật, end-to-end), 1.348 test giao diện, CI và
  hook chặn commit (quét bí mật, test).

## Kết quả chính

Đo trên bản đóng băng `v1.0-freeze` với LLM thật (chi tiết và giới hạn ở báo cáo đồ án):

| Phép đo | Kết quả |
| --- | --- |
| An toàn của lớp LLM (100 kịch bản có nhãn) | Bỏ sót 0/24 tình huống cần người; cận trên 95% là 11,7% |
| Chặn prompt injection (95 câu do người viết, gán nhãn mù) | Nhiều lớp bắt 82%, riêng model nhóm 62%, Prompt Guard 2 20%; chặn nhầm 1/45 câu thường |
| Truy hồi tài liệu (34 bài, bản nộp) | Recall@5 = 1,000; MRR = 0,845 |
| Tái lập | Người thứ hai chạy lại: khớp quyết định 90/90 ca |

Giới hạn đã biết: lợi ích chi phí của cách kết hợp luật và LLM so với chỉ dùng luật **chưa chứng minh được** vì bộ dữ
liệu đánh giá còn nhỏ và độ đồng thuận gán nhãn thấp; hệ thống chạy trên môi trường giả lập, chưa thử với người dùng thật.

## Chạy nhanh (cho thầy và hội đồng)

Cần: Docker Desktop, git, make, Python 3, [uv](https://docs.astral.sh/uv/), Node.js 24 (npm 11). Windows chạy trong WSL2.
RAM 16 GB, ổ trống từ 25 GB, có Internet ở lần chạy đầu. Lần đầu mất khoảng 45–60 phút, chủ yếu là tải model và build.

1. **Lấy mã:** `git clone https://github.com/17tuanphamanh/aip_fa26_g8 && cd aip_fa26_g8`
2. **Đặt file `.env`** nhóm gửi riêng vào thư mục gốc repo (cùng chỗ với `Makefile`). File này chứa khoá API nên không
   nằm trong repo. Không có file này thì tạo theo mục 3 của [hướng dẫn](docs/HUONG-DAN-CHAY.md); khi đó hệ thống chạy LLM giả.
3. **Tải 2 model chung** (bge-m3, bge-reranker-v2-m3; khoảng 4,5 GB): `make models`
4. **Gắn 2 model của nhóm:** giải nén file model nhóm gửi kèm vào thư mục gốc repo, sao cho có
   `ml_models/injection-clf/v3-seed123/` và `ml_models/intent-clf/v3.1-seed42-st/`, rồi chạy `chmod -R a+rX ml_models models`.
   File `.env` đã trỏ sẵn tới hai thư mục này. Máy 8 GB RAM: xoá 3 dòng `INTENT_*` trong `.env`.
5. **Dựng hệ thống:** `make up`, rồi `make ingest` để nạp kho tài liệu (lần đầu 15–25 phút).
6. **Mở giao diện:** ở terminal thứ hai chạy `cd frontend && npm ci && npm run dev`, rồi mở http://localhost:5173 bằng Chrome.
   Mật khẩu chung `Demo@2026!`: `an.nv` (nhân viên), `ha.lt` (IT L1, duyệt phiếu), `long.nh` (kỹ thuật viên L2),
   `quan.tm` (trưởng bộ phận IT, cần đặt OTP một lần theo mục 8 của hướng dẫn). Hệ thống giả lập: http://127.0.0.1:8100/console
7. **Tắt:** `make down` (dữ liệu vẫn giữ).

Hướng dẫn đầy đủ, kể cả lỗi hay gặp: [docs/HUONG-DAN-CHAY.md](docs/HUONG-DAN-CHAY.md).

## Tài liệu

- Hướng dẫn chạy: [docs/HUONG-DAN-CHAY.md](docs/HUONG-DAN-CHAY.md)
- Ảnh chụp demo 10 ca theo từng vai: [docs/anh-demo/AITHA-anh-chup-demo-10-ca.pdf](docs/anh-demo/AITHA-anh-chup-demo-10-ca.pdf)
- Đặc tả và quyết định thiết kế: [docs/spec/](docs/spec/), [docs/spec/build/decisions.md](docs/spec/build/decisions.md)
- Sơ đồ kiến trúc: [docs/kien-truc/](docs/kien-truc/)
- Model của nhóm: [ml_models/MODELS.md](ml_models/MODELS.md)
- Nhật ký tiến độ theo phase: [PROGRESS.md](PROGRESS.md)

> `CLAUDE.md` và thư mục `.claude/` là cấu hình agent hỗ trợ viết code: nhóm dùng Claude Code và có khai báo mức dùng AI
> trong báo cáo đồ án.

## Bản nộp và bản đo

| Mốc | Ở đâu | Dùng cho |
| --- | --- | --- |
| **Bản đo** | tag `v1.0-freeze` (`bf94df2`, 29/10/2026) | Mọi số liệu RQ trong báo cáo đo trên bản này: stack + LLM thật sinh xác suất thô và route của luật. Phương án có LLM (Hybrid, Chỉ-LLM, Hybrid-guarded) được tính lại **offline** bằng kiểm tra chéo 5 phần (`backend/app/eval/offline.py`: fit hiệu chỉnh + chọn ngưỡng trên 4 phần, đo phần còn lại), τ của B2 báo ở 0,50 cũng tính lại offline (D-70). Vì vậy `git checkout v1.0-freeze` chỉ cho lại **mã** đã đo; muốn có lại số phải chạy lại harness rồi chạy `offline.py`: với cache LLM của lượt đo (không có trong repo, chuyển tay theo `docs/HUONG-DAN-CHAY.md` mục 11.3) thì ra lại đúng lời gọi cũ; không có cache thì gọi LLM thật và số có thể lệch vì LLM không tất định — xem `backend/app/eval/README.md`. |
| **Bản nộp** | nhánh `main` (14/11/2026) | Mã nguồn nộp và video demo. Gồm bản đo + mọi thay đổi sau đó (sửa lỗi sau buổi test của giám khảo, các lô Q1–Q13). Phần khác bản đo ghi ở báo cáo mục "Bản nộp khác bản đo" và [PROGRESS.md](PROGRESS.md). |

Hệ thống: LangGraph B1→B20 (sàng lọc → phân loại → chẩn đoán → trả lời KB hoặc thực thi có duyệt → kiểm chứng → audit),
FastAPI + PostgreSQL + Qdrant + ml-service (embed, rerank, phân loại) + mock AD/VPN/phần mềm/file server, giao diện React.
Quyết định thiết kế đánh số D-xx ở [docs/spec/build/decisions.md](docs/spec/build/decisions.md).

### Cờ tính năng của bản nộp (`.env`, mặc định đều bật)

Bốn tính năng lớn thêm sau bản đo có cờ riêng; đặt `false` là tắt riêng tính năng đó (quay về hành vi trước khi có nó), không cần đổi code. Các sửa đổi khác sau bản đo (D-75, D-77, D-81, luật R21, mẫu chặn SYS-04, biến thể câu lặp Q13c, vai chat Q10) KHÔNG có cờ — muốn đúng hành vi bản đo thì chạy tag `v1.0-freeze`.

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
| `docs/` | Hướng dẫn chạy (`HUONG-DAN-CHAY.md`), sơ đồ kiến trúc (`kien-truc/`, trỏ sang đặc tả) |
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
