"""Store của gateway cho run rq2 — theo Protocol `app.llm.ports.LlmStore`, mọi thứ nằm trong thư mục run (không PG).

- Cache (a): `<run>/cache_a/<khoá>.json` — cùng khoá `cache_key` của gateway; mode `eval` không hết hạn. Chạy lại → đọc file, 0 lời gọi mạng.
- `record`: một dòng `<run>/llm_calls_a.jsonl` (như `llm_calls`, `prompt_full` giữ khi EVAL_MODE) + chi phí vào sổ chi.
- `requires_trace = False`: lời gọi ngoài lượt graph (như `MemoryLlmStore` của test) — không có dòng `spans`/`llm_calls` trong PG.
- Sổ chi `<run>/spend.jsonl` dùng chung cho (a) và (c); `spend_total` = tổng sổ → trần `--max-usd` của run (`SpendTracker` của gateway
  cho (a), `logprob.LogprobClient` cho (c)). Trần KHÔNG cộng `SUM(llm_calls.cost_usd)` của PG (trần 38 USD của đồ án).
"""

import json
import os
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from app.llm.ports import CacheMode, LlmCallRow, LlmSpan

KEY = re.compile(r"[0-9a-f]{64}")
SPEND_NOTE: Final = "trần --max-usd chỉ tính chi của run rq2 này (spend.jsonl), KHÔNG cộng SUM(llm_calls.cost_usd) của PG"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class SpendLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def total(self) -> float:
        return float(sum(float(r["cost_usd"]) for r in _rows(self.path)))

    def add(self, source: Literal["a", "c"], cost_usd: float) -> None:
        if cost_usd:
            _append(self.path, {"source": source, "cost_usd": cost_usd})


class FileLlmStore:
    requires_trace = False

    def __init__(self, run_dir: Path, ledger: SpendLedger) -> None:
        self.cache_dir = run_dir / "cache_a"
        self.calls_path = run_dir / "llm_calls_a.jsonl"
        self.ledger = ledger

    def _path(self, key: str) -> Path:
        if not KEY.fullmatch(key):
            raise ValueError("khoá cache lạ")
        return self.cache_dir / f"{key}.json"

    async def cache_get(self, key: str, *, mode: CacheMode, now: datetime) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        row = json.loads(path.read_text(encoding="utf-8"))
        if row["mode"] != mode:
            return None
        return dict(row["response"])

    async def cache_put(
        self, key: str, *, mode: CacheMode, prompt_id: str, prompt_version: str, model: str, response: dict[str, Any],
        now: datetime, expires_at: datetime | None,
    ) -> None:  # fmt: skip
        row = {"mode": mode, "prompt_id": prompt_id, "prompt_version": prompt_version, "model": model, "response": response,
               "created_at": now.isoformat()}  # fmt: skip
        write_atomic(self._path(key), json.dumps(row, ensure_ascii=False, sort_keys=True))

    async def record(self, span: LlmSpan, call: LlmCallRow) -> None:
        _append(self.calls_path, {**asdict(call), "attributes": span.attributes})
        self.ledger.add("a", call.cost_usd)

    async def spend_total(self) -> float:
        return self.ledger.total()

    def calls(self) -> list[dict[str, Any]]:
        return _rows(self.calls_path)
