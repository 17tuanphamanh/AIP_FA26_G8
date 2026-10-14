"""Test M8 (`app.eval`) — chặn `EVAL_MODE` (P8 §8, Q-T29-2 chốt 13/10 ở #32).

`app/eval/__init__.py` từ chối import khi `EVAL_MODE ≠ true`. Bật cờ đúng MỘT lần quanh `importlib.import_module("app.eval")`
rồi trả env ngay: module con (`app.eval.predictions`…) import sau không chạy lại `__init__`, nên không test nào — trong hay ngoài
thư mục này — thấy `EVAL_MODE=true` (`test_eval_mode_guard.py`, `../test_eval_mode_isolation.py`). Không sửa Makefile.
"""

import importlib
import os
from unittest import mock

import pytest

EVAL_MODE_BEFORE = os.environ.get("EVAL_MODE")

with mock.patch.dict(os.environ, {"EVAL_MODE": "true"}):
    importlib.import_module("app.eval")


@pytest.fixture
def eval_mode_before() -> str | None:
    """Giá trị `EVAL_MODE` trước khi conftest bật cờ (thường là không có)."""
    return EVAL_MODE_BEFORE
