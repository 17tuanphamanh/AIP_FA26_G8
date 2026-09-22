# AIP_FA26_G8

Cài  : .venv/bin/python -m pip install -r requirements.txt
Test : .venv/bin/python -m pytest -q
Chạy : .venv/bin/python main.py "câu hỏi"   — bỏ tham số là vào chế độ chat

## Cách làm việc

- **Làm trọn việc rồi mới báo cáo.** Sửa xong thì chạy test, đọc kết quả, rồi mới
  quay lại. Đừng dừng hỏi sau từng bước nhỏ — trừ khi có hai hướng khác hẳn nhau
  mà chọn sai thì phải làm lại từ đầu.
- **Việc dài thì lên kế hoạch trước** (Plan Mode, Shift+Tab). Rẻ hơn nhiều so với
  đi sai hướng rồi sửa.
- **Báo cáo trung thực.** Test đỏ thì nói đỏ kèm output. Bỏ qua bước nào thì nói rõ.
  Đừng viết "đã xong" cho phần chưa chạy thử.
- **Không commit, không push trừ khi được bảo.** Commit không để dấu vết AI.

## Ranh giới

- Đổi phụ thuộc thì sửa `requirements.txt`, đừng cài ngầm vào máy.
- Bí mật nằm ở `.env` (đã gitignore) — không đọc, không ghi, không in ra. Không dán
  key vào prompt, log hay chỗ chat. `.env.example` là file mẫu công khai, sửa thoải mái.
- `data/` chỉ đọc, không ghi đè. File sinh tự động (cache, lockfile) thì sửa nguồn.
- **File untracked là việc chưa ai lưu.** Không xoá, không `git clean`, khi chưa hỏi —
  git không giữ bản sao nào để lấy lại.

## Ghi chú riêng của repo

### Luồng chạy

`main.py` → `Agent.ask()` (`agent/core.py`) → `tool_runner` của SDK → `agent/tools.py`
→ kết quả nạp ngược lại model, lặp đến khi model thôi gọi tool. Vẽ đầy đủ ở
`docs/kien-truc.md`. System prompt nằm ở `agent/prompts/system.md`.

### Thêm một tool

1. Viết hàm Python thuần trong `agent/tools.py` — test được, không cần API.
2. Viết bản bọc `@beta_tool` gọi vào hàm đó. **Docstring chính là schema model đọc**
   để quyết định khi nào gọi; SDK suy kiểu tham số từ type hint.
3. Thêm vào danh sách `TOOLS`.
4. Viết test trong `tests/test_tools.py`.

### Chỗ hay sai

- **`_safe_path()` là rào chắn, chặn HAI thứ** — đừng gỡ cho tiện, tool nào đụng
  file cũng phải đi qua nó:
  1. đường dẫn ra ngoài repo (`../../etc/passwd`, `/etc/passwd`);
  2. bí mật *nằm trong* repo — `.env`, `.env.*`, `.git/`, `*.key`, `*.pem`,
     `secrets/` — vì rào (1) không với tới chúng. `.env.example` vẫn đọc được.
  Bí mật bị từ chối kể cả khi file không tồn tại, nên thông báo lỗi không tiết lộ
  file nào đang có. Test ghim: `test_read_file_rejects_a_path_outside_the_repo`,
  `test_read_file_refuses_the_env_file`,
  `test_refusing_a_secret_does_not_reveal_whether_it_exists`.
- **Test không được gọi API thật.** Cả `tests/` hiện chạy bằng key giả, không tốn
  lượt nào. Muốn thử model thật thì chạy tay `main.py`, đừng nhét vào test.
- **Đổi tên biến cấu hình phải sửa đủ 3 chỗ**: `agent/config.py`, `.env.example`, và
  test đang ghim tên đó (`test_max_steps_is_read_from_environment`).
- **Đã có `data/` rồi, đừng tạo thư mục dữ liệu tên khác.** `.gitignore` chỉ chừa
  `data/*`; thư mục khác (`du_lieu/`…) sẽ lọt thẳng vào git kèm dữ liệu nặng.
- Sửa `system.md` hay docstring tool là **đổi hành vi agent** — phải chạy lại thử,
  không phải sửa xong báo xong.
- `CHAR_LIMIT` trong `tools.py` cắt file dài, để một file không nhét đầy context.
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

- `.githooks/pre-commit` — đụng file `.py` **hoặc** `agent/prompts/*.md` thì `pytest`
  phải xanh mới cho commit. Không thấy `.venv` thì cũng chặn, thay vì báo "test đỏ"
  sai sự thật. Nó lấy **hợp** của `git diff --cached` và `git diff HEAD` nên
  `git commit -a` không lách được.
- `.githooks/commit-msg` — chặn `Co-Authored-By: Claude`, `Claude-Session`, link
  `claude.ai`, `noreply@anthropic.com`, emoji robot. Lọc bỏ dòng `#` trước khi soi
  nên `git commit -v` (nhét cả diff vào comment) không báo động giả.

Cố tình bỏ qua cả hai: `git commit --no-verify`.

`.claude/hooks/pre-commit-test.sh` chỉ là lớp mỏng gọi lại `.githooks/pre-commit`,
để Claude chặn sớm hơn một nhịp. **Sửa luật soát thì sửa ở `.githooks/`**, đừng sửa
lớp mỏng đó. Cấu hình trong `.claude/` còn phải được *trust* mới chạy — ai clone về
phải mở `claude` tương tác một lần ở thư mục repo rồi bấm đồng ý, không thì CLI báo
`Ignoring N permissions.allow entries ... not been trusted`.
