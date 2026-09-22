#!/bin/bash
# Lớp mỏng cho Claude Code — gọi thẳng hook git ở .githooks/pre-commit, để logic
# soát test chỉ nằm MỘT chỗ. Sửa luật soát thì sửa bên đó, đừng sửa file này.
#
# Vì sao vẫn giữ lớp này khi đã có hook git:
#   - Nó chặn SỚM hơn, trước khi lệnh git kịp chạy.
#   - Nó vẫn gác kể cả khi ai đó quên `git config core.hooksPath .githooks`.
#
# Khác biệt duy nhất là mã thoát: PreToolUse cần exit 2 mới chặn được tool call,
# exit 1 chỉ là lỗi thường và KHÔNG chặn.
#
# Rà 22/09/2026 — bỏ `cd ... || exit 0`. Hướng hỏng cũ là im lặng cho qua:
# biến rỗng thì hook thoát 0 và commit lọt. Giờ hỏng ở đâu cũng chặn.
set -u

repo="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
if [ -z "$repo" ] || [ ! -d "$repo" ]; then
  echo "Không xác định được thư mục repo — không soát được test." >&2
  exit 2
fi
cd "$repo" || { echo "Không vào được $repo." >&2; exit 2; }

if [ ! -x .githooks/pre-commit ]; then
  echo "Thiếu .githooks/pre-commit — không soát được test." >&2
  exit 2
fi

.githooks/pre-commit || exit 2
exit 0
