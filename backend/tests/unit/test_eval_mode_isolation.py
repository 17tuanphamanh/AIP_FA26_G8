"""Q-T29-2 — test ngoài `tests/unit/eval/` không thấy `EVAL_MODE=true`.

`tests/unit/eval/conftest.py` bật cờ quanh một lần import `app.eval` rồi trả env. Conftest được nạp lúc THU THẬP, trước khi mọi
test chạy — nên khi chạy cùng thư mục eval (`make test`, `pytest backend/tests/unit`), test này đỏ nếu conftest để rò cờ
(`EVAL_MODE=true` làm `Settings` bật `prompt_full` cho các test khác, P2 mục 11).
"""

import os


def test_eval_mode_not_visible_outside_eval_tests() -> None:
    assert os.environ.get("EVAL_MODE", "").strip().lower() != "true"
