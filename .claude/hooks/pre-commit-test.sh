#!/bin/bash
# Chặn commit khi test đỏ. Chạy bằng PreToolUse hook, xem .claude/settings.json.
# exit 2 = chặn tool call. exit 1 chỉ là lỗi thường, KHÔNG chặn được.
cd "$CLAUDE_PROJECT_DIR" || exit 0

# Chỉ chạy test khi commit thực sự đụng file mã nguồn.
files=$(git diff --cached --name-only)
[ -z "$files" ] && files=$(git diff --name-only HEAD)
echo "$files" | grep -qE '\.py$' || exit 0

if ! .venv/bin/python -m pytest -q; then
  echo "Test đỏ — sửa xong rồi hãy commit." >&2
  exit 2
fi
exit 0
