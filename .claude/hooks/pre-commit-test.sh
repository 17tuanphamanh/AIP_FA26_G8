#!/bin/bash
# Chặn commit khi test đỏ. Chạy bằng PreToolUse hook, xem .claude/settings.json.
# exit 2 = chặn tool call. exit 1 chỉ là lỗi thường, KHÔNG chặn được.
cd "$CLAUDE_PROJECT_DIR" || exit 0

# Rà 22/09/2026 — vá lỗ `git commit -a`.
# Bản cũ: lấy --cached, RỖNG thì mới ngó `git diff HEAD`. Nên khi đã stage một
# file .md trong lúc vài file .py đang bẩn, `git commit -a` gom hết .py vào
# commit mà hook thấy danh sách toàn .md rồi bỏ qua test. Đúng tình huống đã
# xảy ra: staged = docs/quy-uoc-du-an.md, 8 file .py bẩn.
# Giờ lấy HỢP của hai tập. pytest ở repo này chạy 1.0s — chạy thừa vài lần rẻ
# hơn nhiều so với lọt một commit đỏ.
files=$(
  git diff --cached --name-only
  git diff --name-only HEAD
)
printf '%s\n' "$files" | grep -qE '\.py$' || exit 0

# Không có .venv thì nói thẳng, đừng để pytest hỏng rồi báo "test đỏ" sai sự thật.
if [ ! -x .venv/bin/python ]; then
  echo "Không thấy .venv/bin/python — chưa dựng môi trường, không soát được test." >&2
  echo "Dựng bằng: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 2
fi

if ! .venv/bin/python -m pytest -q; then
  echo "Test đỏ — sửa xong rồi hãy commit." >&2
  exit 2
fi
exit 0
