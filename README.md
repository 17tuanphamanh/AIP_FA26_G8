# AIP_FA26_G8 — Đồ án AI Agent

Repo đồ án môn AIP, kỳ Fall 2026, nhóm 8.
Khung một **AI agent**: nhận câu hỏi bằng tiếng Việt, tự gọi các *tool* (đọc file, liệt kê thư mục…) rồi trả lời.

## Chạy thử trong 4 bước

```bash
# 1. Tạo môi trường ảo + cài thư viện
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Khai báo API key (KHÔNG commit file .env)
cp .env.example .env
#    rồi mở .env, điền ANTHROPIC_API_KEY thật vào

# 3. Chạy test cho chắc
.venv/bin/python -m pytest

# 4. Chạy agent
.venv/bin/python main.py "Trong repo này có những thư mục nào?"
.venv/bin/python main.py          # chế độ chat, gõ 'thoat' để dừng
```

## Cấu trúc thư mục

| Đường dẫn | Chứa gì |
| --- | --- |
| `main.py` | Điểm chạy: hỏi đáp trong terminal |
| `agent/config.py` | Đọc cấu hình từ `.env` (API key, model, giới hạn) |
| `agent/core.py` | Vòng lặp agent — gọi model, để nó tự dùng tool |
| `agent/tools.py` | Các tool agent được phép gọi |
| `agent/prompts/system.md` | System prompt — quy định cách agent hành xử |
| `tests/` | Test chạy được mà không cần gọi API |
| `docs/` | Đề bài, kiến trúc, nhật ký nhóm |
| `notebooks/` | Notebook thử nghiệm |
| `data/` | Dữ liệu — **không** commit lên git |

## Thêm một tool mới

Mở [agent/tools.py](agent/tools.py):

1. Viết hàm Python thuần (dễ test).
2. Viết bản bọc `@beta_tool` gọi vào hàm đó — **docstring chính là thứ model đọc** để biết khi nào dùng tool, viết cho rõ.
3. Thêm vào `DANH_SACH_TOOL`.
4. Viết test trong `tests/test_tools.py`.

## Quy ước làm việc chung

- **Không commit `.env`, dữ liệu nặng, `.venv/`** — đã chặn sẵn trong `.gitignore`. Nếu lỡ commit key thì phải vào trang nhà cung cấp **thu hồi (revoke) key ngay**, xoá dòng code là không đủ.
- Message commit ghi rõ làm được gì, tiếng Việt không dấu — ví dụ `them tool tim kiem tai lieu, test pass`. Tránh `update`, `fix bug`.
- Trước khi commit: `git status` → `git diff` → chạy `pytest` → mới `git add -A`.
- Mỗi người làm xong phần của mình thì `git pull` trước, rồi mới `git push`.


