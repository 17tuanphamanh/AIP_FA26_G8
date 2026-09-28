"""Tìm tokenizer bge-m3 thật cho test `tokenizer_real` (PLAN-3b mục 8, Q-3b-11).

Revision lấy từ `ml_service/models.lock.json` (mục `embed`). Thứ tự tìm: env `TOKENIZER_DIR` →
`models/_tokenizer/BAAI/bge-m3@<rev>/tokenizer.json` (`make tokenizer`) → `models/BAAI/bge-m3@<rev>/tokenizer.json`
(`make models`). Không thấy: CI (`CI=true`) → FAIL (không để test thật lặng lẽ bị bỏ qua); máy dev → skip.
"""

import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
LOCK = REPO / "ml_service" / "models.lock.json"


def bge_m3_tokenizer_path() -> Path | None:
    entry = json.loads(LOCK.read_text(encoding="utf-8"))["embed"]
    name = f"{entry['repo']}@{entry['revision']}"
    candidates = []
    if os.environ.get("TOKENIZER_DIR"):
        candidates.append(Path(os.environ["TOKENIZER_DIR"]) / name / "tokenizer.json")
    candidates += [REPO / "models" / "_tokenizer" / name / "tokenizer.json", REPO / "models" / name / "tokenizer.json"]
    return next((p for p in candidates if p.is_file()), None)


def require_bge_tokenizer() -> Path:
    """Dùng trong fixture: trả đường dẫn tokenizer.json, hoặc skip (máy dev) / fail (CI)."""
    path = bge_m3_tokenizer_path()
    if path is not None:
        return path
    if os.environ.get("CI") == "true":
        pytest.fail("thiếu tokenizer bge-m3 — make tokenizer")
    pytest.skip("chưa có tokenizer bge-m3 — chạy make tokenizer")
