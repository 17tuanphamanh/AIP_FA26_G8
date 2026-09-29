# AIP_FA26_G8 — servicedesk-agent

**Đặc tả ở `docs/spec/` — đọc `docs/spec/CLAUDE.md` trước mọi task.** Mọi đường dẫn
tài liệu trong đặc tả tính từ `docs/spec/`. Tiến độ, cổng phase và câu hỏi mở ghi ở
`PROGRESS.md`.

**Chế độ xây hiện tại: code trước, gắn API sau** (`docs/spec/build/decisions.md` mục 4).
Phase 1–7 không gọi LLM thật, không thêm API key; phần cổng cần LLM thật ghi vào
`PROGRESS.md` mục "Dồn về mốc G" rồi đi tiếp.

Cài  : uv sync                 — Python 3.12; model nặng của ml-service: uv sync --group ml
Test : make test               — hoặc uv run pytest
Lint : make lint

## Cách làm việc

- **Làm trọn việc rồi mới báo cáo.** Sửa xong thì chạy test, đọc kết quả, rồi mới
  quay lại. Đừng dừng hỏi sau từng bước nhỏ — trừ khi có hai hướng khác hẳn nhau
  mà chọn sai thì phải làm lại từ đầu.
- **Mâu thuẫn trong đặc tả chính là trường hợp "hai hướng khác hẳn nhau"** — dừng,
  ghi vào `PROGRESS.md`, hỏi người. Không tự chọn một bên.
- **Việc dài thì lên kế hoạch trước** (Plan Mode, Shift+Tab). Rẻ hơn nhiều so với
  đi sai hướng rồi sửa.
- **Báo cáo trung thực.** Test đỏ thì nói đỏ kèm output. Bỏ qua bước nào thì nói rõ.
  Đừng viết "đã xong" cho phần chưa chạy thử.
- **Không commit, không push trừ khi được bảo.** Commit không để dấu vết AI.
- **Sau mỗi lần push, theo dõi CI:** `gh run list --branch <nhánh> -L 1` lấy id, rồi
  `gh run watch <id>`, báo xanh/đỏ. Đỏ thì `gh run view <id> --log-failed` và báo
  nguyên nhân. Chỉ dùng lệnh `gh` chỉ đọc (`run list/view/watch`). Lệnh `gh` bị sandbox
  chặn (mạng/keychain) → báo người, không tự nới quyền.

## Ranh giới

- Đổi phụ thuộc thì sửa `pyproject.toml` (`uv add` / `uv remove`, `uv.lock` đi kèm),
  đừng cài ngầm vào máy.
- Bí mật nằm ở `.env` (đã gitignore) — không đọc, không ghi, không in ra. Không dán
  key vào prompt, log hay chỗ chat. `.env.example` là file mẫu công khai, sửa thoải mái.
- **Dữ liệu:** dữ liệu huấn luyện ở `training/data/` (gitignore) — chỉ đọc, không ghi
  đè. KB ở `kb/`, kịch bản ở `eval/` — hai chỗ này **được commit**. Đừng tạo thư mục
  dữ liệu tên khác. File sinh tự động (cache, `uv.lock`) thì sửa nguồn.
- **File untracked là việc chưa ai lưu.** Không xoá, không `git clean`, khi chưa hỏi —
  git không giữ bản sao nào để lấy lại.

## Ghi chú riêng của repo

### Chỗ hay sai

- **Test không gọi LLM thật** — dùng `ScriptedLLM` (`backend/tests/fakes/`). Probe với
  LLM thật nằm ở `backend/tests/probe/`, chạy riêng bằng `make probe`, không nằm trong
  `make test`.
- Sửa `config/prompts/*` hay `config/policy.json` là **đổi hành vi agent** — phải chạy
  lại thử, không phải sửa xong báo xong.
- `.gitignore` chặn `*.csv`, `*.zip`, `*.onnx`… trên **toàn repo**. Ngoại lệ duy nhất:
  CSV nguồn của báo cáo thực nghiệm trong `eval/reports/` (P8). Cần commit loại file
  khác thì hỏi trước khi thêm luật ngoại lệ.
- `.claude/settings.local.json` là quyền riêng từng người, **đã gitignore** — đừng
  `git add -f` nó lên. Quyền dùng chung thì sửa `.claude/settings.json`.
- **Mẫu quyền trong `settings.json`: dấu cách trước `*` là một phần của luật.**
  `Bash(git commit *)` khớp cả `git commit` trần; `Bash(git commit*)` thì khớp lây
  sang `git commitfoo`. Đừng bỏ dấu cách đi.
- **Luật `ask` không phải hàng rào an ninh.** Nó khớp theo chữ của lệnh, nên
  `/usr/bin/pip install ...` hay `sh -c '...'` đi lọt. Nó để chống lỡ tay, không
  chống cố ý — rào thật là sandbox và hook git.

### Hook chặn commit

Hai hook **của git**, nằm ở `.githooks/` nên đi theo repo. Mỗi bản clone phải bật
một lần, không bật thì không có gì gác:

```
git config core.hooksPath .githooks
```

Hook soát (chi tiết + lý do trong chú thích `.githooks/pre-commit`, `.githooks/commit-msg`):
gitleaks với MỌI commit (thiếu `gitleaks` cũng chặn); đụng `.py`, `config/prompts/*`,
`config/policy.json` thì unit test phải xanh; commit-msg chặn dấu vết AI.
Cấm `git commit --no-verify`.
Mỗi người cài hook một lần sau khi clone: `git config core.hooksPath .githooks`.

`.claude/hooks/pre-commit-test.sh` chỉ là lớp mỏng gọi lại `.githooks/pre-commit`,
để Claude chặn sớm hơn một nhịp. **Sửa luật soát thì sửa ở `.githooks/`**, đừng sửa
lớp mỏng đó. Cấu hình trong `.claude/` còn phải được *trust* mới chạy — ai clone về
phải mở `claude` tương tác một lần ở thư mục repo rồi bấm đồng ý, không thì CLI báo
`Ignoring N permissions.allow entries ... not been trusted`.
