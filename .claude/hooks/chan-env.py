"""PreToolUse: chặn Read/Edit/Write/MultiEdit/NotebookEdit/Grep/Glob đụng file .env* (trừ .env.example).

Vì sao cần: deny rule ở ~/.claude/settings.json chỉ liệt kê vài tên (.env, .env.local,
.env.production…) và nằm ở máy từng người; sandbox thì chỉ gác lệnh Bash. Read/Grep/Glob
với tên khác (.env.hooktest, .env.staging…) đi lọt. Hook này gác theo basename và đi theo repo.

Chỉ nhìn đường dẫn trong tool_input, KHÔNG mở file. `pattern` của Grep là regex tìm nội dung
nên không soát (tìm chữ ".env" trong code là hợp lệ); nội dung file .env* khỏi bị Grep quét
là nhờ .gitignore (`.env*`) — ripgrep bỏ qua file bị ignore.

Đầu vào hỏng (không phải JSON object) thì chặn — cùng hướng với pre-commit-test.sh: hỏng ở
đâu cũng chặn. PreToolUse cần exit 2 mới chặn được; exit 1 chỉ là lỗi thường, tool vẫn chạy.
"""

import json
import re
import sys

THONG_BAO = "Chan: khong doc/sua file .env* (tru .env.example)"
_ENV = re.compile(r"^\.env", re.IGNORECASE)
_KHOA_DUONG_DAN = ("file_path", "path", "notebook_path", "glob")


def _cac_duong_dan(tool_name, tool_input):
    for khoa in _KHOA_DUONG_DAN:
        gia_tri = tool_input.get(khoa)
        if isinstance(gia_tri, str):
            yield gia_tri
    # Với Glob, `pattern` là mẫu đường dẫn; với Grep nó là regex nội dung — bỏ qua.
    if tool_name == "Glob" and isinstance(tool_input.get("pattern"), str):
        yield tool_input["pattern"]


def _la_file_env(duong_dan):
    ten = re.split(r"[\\/]", duong_dan.rstrip("/\\"))[-1]
    return bool(_ENV.match(ten)) and ten != ".env.example"


def main():
    try:
        du_lieu = json.load(sys.stdin)
        tool_name = du_lieu.get("tool_name", "")
        tool_input = du_lieu.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            raise TypeError
    except (ValueError, AttributeError, TypeError):
        print("Chan: hook chan-env khong doc duoc dau vao", file=sys.stderr)
        return 2
    if any(_la_file_env(p) for p in _cac_duong_dan(tool_name, tool_input)):
        print(THONG_BAO, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
