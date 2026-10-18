"""Hàm dùng chung cho test gói 1 (B2 `review`, D-52) — không phải file test (tên bắt đầu `_`, pytest không gom).

Nguồn: `PLAN-B2REVIEW.md` mục 4 + mục 8 ("Script nạp bằng `importlib.util.spec_from_file_location` như
`test_rule_coverage.py`"); `docs/spec/claude/dac-ta-bat-2-model.md` mục 3, 4.5, 6.1, 9.2, 9.3.

- `load_script(rel, monkeypatch)`: nạp `scripts/...py` bằng importlib dưới tên riêng. Thư mục của script được đặt đầu
  `sys.path` (qua `monkeypatch.syspath_prepend`, trả lại sau test) — giống khi chạy `python scripts/eval/x.py`, để script
  import được script anh em (`_pii_fake`, `b2_judge_compare`…).
- `It`: phần tử đầu vào dạng `{id, text, label, group}` đọc được cả kiểu `it["id"]` lẫn `it.id` — mục 8 không ghim kiểu
  phần tử của `prepare_rows(items)` (dict hay `Item`), test không đoán.
- `write_jsonl`: ghi file JSONL (UTF-8, `ensure_ascii=False`).
"""

import importlib.util
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "config"


def load_script(rel: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = REPO / rel
    monkeypatch.syspath_prepend(str(path.parent))
    name = "_b2review_" + path.stem.lstrip("_")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"không nạp được {rel}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class It(dict[str, Any]):
    """dict đọc được bằng thuộc tính (`it.id`)."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def item(id: str, text: str, label: str = "normal", group: str = "g0") -> It:
    return It(id=id, text=text, label=label, group=group)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(dict(r), ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
