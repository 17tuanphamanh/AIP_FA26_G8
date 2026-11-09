"""M5 — tỉ số token THẬT / ƯỚC LƯỢNG của gateway LLM, theo `prompt_id` (trung vị, p95). CHỈ ĐỌC; không đổi gì ở runtime.

Gateway ước lượng token bằng `ceil(ký tự / 3)` (`app.llm.context.estimate_tokens`; chưa đo trên tokenizer của LLM — Q-3d-8) để cắt `budget_in` và
giữ chỗ trần chi. Script này đo độ lệch của ước lượng đó so với số token nhà cung cấp báo, để mốc G hiệu chỉnh:

    PYTHONPATH=backend uv run python scripts/eval/token_estimate_check.py --dsn <DSN role app_monitor> [--since 2026-11-01] [--min-n 30]

Tỉ số = thật / ước lượng. > 1: ước lượng ĐẾM THIẾU (budget_in cắt chậm hơn thật, trần chi giữ chỗ thiếu); < 1: đếm thừa.

- **Thật** = `llm_calls.tokens_in`. `_account` của gateway cộng dồn MỌI lần thử và rơi về chính ước lượng khi nhà cung cấp không báo usage, nên
  chỉ nhận dòng sạch: không cache, không lỗi, không fallback, đúng MỘT lần thử, có `usage_tokens_in` (span) và `tokens_in == usage_tokens_in`.
  Dòng bị loại được đếm theo lý do ở cuối bảng (không bỏ lặng lẽ).
- **Ước lượng** = dựng lại từ `llm_calls.prompt_full` (chỉ có khi EVAL_MODE) bằng chính `estimate_tokens` trên từng message (không phải độ dài
  chuỗi JSON); không có thì lấy `est_tokens_in` của span (cùng giá trị gateway đã tính lúc gửi). Hai nguồn lệch nhau được đếm.

An toàn: một câu SELECT duy nhất; phiên đặt `default_transaction_read_only=on` (kể cả khi DSN nhầm sang role ghi được vẫn không ghi); DSN chỉ nhận
qua `--dsn` (không đọc cấu hình ứng dụng) và không bao giờ được in ra; thông báo lỗi chỉ có tên lớp ngoại lệ. Khuyến nghị DSN của role `app_monitor`.
Không chạy trên máy đo. Test: `backend/tests/unit/test_token_estimate_check_m5.py` (dữ liệu tổng hợp).

Mã thoát: 0 có số; 1 không có dòng sạch nào; 2 sai cách dùng / không đọc được DB.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from typing import Any

from app.llm.context import estimate_tokens
from sqlalchemy import Engine, create_engine, text

DEFAULT_MIN_N = 30

# MỘT câu SELECT (không dấu chấm phẩy). `->>` trả NULL cho thuộc tính thiếu hoặc JSON null.
QUERY = """
SELECT c.prompt_id, c.prompt_version, c.tokens_in, c.cache_hit, c.used_fallback,
       CASE WHEN c.error IS NULL THEN NULL ELSE 'error' END AS error,
       c.prompt_full,
       (s.attributes ->> 'usage_tokens_in')::int AS usage_tokens_in,
       (s.attributes ->> 'est_tokens_in')::int AS est_tokens_in,
       (s.attributes ->> 'attempts')::int AS attempts
FROM llm_calls c
LEFT JOIN spans s ON s.span_id = c.span_id
WHERE (CAST(:since AS timestamptz) IS NULL OR c.created_at >= CAST(:since AS timestamptz))
ORDER BY c.call_id
"""


@dataclass
class Group:
    ratios: list[float] = field(default_factory=list)
    est_from_prompt_full: int = 0
    est_from_span: int = 0

    @property
    def n(self) -> int:
        return len(self.ratios)

    @property
    def median(self) -> float:
        return float(median(self.ratios))

    @property
    def p95(self) -> float:
        return percentile(self.ratios, 0.95)


@dataclass
class Report:
    groups: dict[str, Group] = field(default_factory=dict)
    excluded: Counter[str] = field(default_factory=Counter)
    est_mismatch: int = 0  # dòng sạch mà ước lượng dựng từ prompt_full ≠ est_tokens_in của span


def percentile(values: Sequence[float], q: float) -> float:
    """Phân vị `q` ∈ [0, 1], nội suy tuyến tính giữa hai hạng gần nhất (như numpy mặc định)."""
    if not values:
        raise ValueError("không có giá trị")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def estimate_from_messages(prompt_full: str) -> int:
    """Ước lượng của gateway dựng lại từ `prompt_full` (JSON danh sách message): tổng `estimate_tokens(content)` TỪNG message —
    đúng cách `llm.context.render` cộng (system, user), không phải `ceil(len(JSON)/3)`. Sai dạng → ValueError."""
    messages = json.loads(prompt_full)
    if not isinstance(messages, list) or not all(isinstance(m, dict) and isinstance(m.get("content"), str) for m in messages):
        raise ValueError("prompt_full không phải danh sách message")
    return sum(estimate_tokens(m["content"]) for m in messages)


def _exclusion(r: Mapping[str, Any]) -> str | None:
    if r.get("cache_hit"):
        return "cache_hit"
    if r.get("error"):
        return "error"
    if r.get("used_fallback"):
        return "fallback"
    if r.get("attempts") != 1:
        return "retry"  # nhiều lần thử: tokens_in cộng dồn các lần, ước lượng chỉ của MỘT lần (attempts thiếu cũng không tin được)
    tokens = r.get("tokens_in")
    if tokens is None or tokens <= 0:
        return "no_tokens"
    if r.get("usage_tokens_in") is None:
        return "no_usage"  # nhà cung cấp không báo → tokens_in chính là ước lượng, tỉ số giả 1,0
    if tokens != r["usage_tokens_in"]:
        return "usage_mismatch"
    return None


def summarize(rows: Iterable[Mapping[str, Any]]) -> Report:
    rep = Report()
    for r in rows:
        reason = _exclusion(r)
        est: int | None = None
        source = "span"
        if reason is None:
            if r.get("prompt_full") is not None:
                try:
                    est, source = estimate_from_messages(str(r["prompt_full"])), "prompt_full"
                except ValueError:  # json.JSONDecodeError là ValueError
                    reason = "bad_prompt_full"
            else:
                est = r.get("est_tokens_in")
            if reason is None and (est is None or est <= 0):
                reason = "no_estimate"
        if reason is not None:
            rep.excluded[reason] += 1
            continue
        assert est is not None
        group = rep.groups.setdefault(str(r["prompt_id"]), Group())
        group.ratios.append(int(r["tokens_in"]) / est)
        if source == "prompt_full":
            group.est_from_prompt_full += 1
            if r.get("est_tokens_in") is not None and r["est_tokens_in"] != est:
                rep.est_mismatch += 1
        else:
            group.est_from_span += 1
    return rep


def render(rep: Report, min_n: int) -> str:
    lines = [f"{'prompt_id':<24} {'n':>6} {'trung vị':>9} {'p95':>8}   nguồn ước lượng (prompt_full/span)"]
    for pid in sorted(rep.groups):
        g = rep.groups[pid]
        flag = f"  (n<{min_n})" if g.n < min_n else ""
        lines.append(f"{pid:<24} {g.n:>6} {g.median:>9.3f} {g.p95:>8.3f}   {g.est_from_prompt_full}/{g.est_from_span}{flag}")
    lines += [
        "",
        "tỉ số = token thật / ước lượng ceil(ký tự/3). > 1: ước lượng ĐẾM THIẾU; < 1: đếm thừa. Chỉ dòng sạch (một lần thử, không cache/lỗi/fallback).",
    ]
    if rep.excluded:
        lines.append("loại: " + ", ".join(f"{k}={v}" for k, v in sorted(rep.excluded.items())))
    if rep.est_mismatch:
        lines.append(f"CẢNH BÁO: {rep.est_mismatch} dòng có ước lượng dựng từ prompt_full ≠ est_tokens_in của span.")
    return "\n".join(lines)


def make_engine(dsn: str) -> Engine:
    return create_engine(dsn, connect_args={"options": "-c default_transaction_read_only=on"})


def fetch_rows(dsn: str, since: datetime | None) -> list[dict[str, Any]]:
    engine = make_engine(dsn)
    try:
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(text(QUERY), {"since": since}).mappings().all()]
    finally:
        engine.dispose()


def _since(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def main(argv: Sequence[str] | None = None, fetch: Callable[[str, datetime | None], Iterable[Mapping[str, Any]]] = fetch_rows) -> int:
    ap = argparse.ArgumentParser(description="Tỉ số token thật / ước lượng theo prompt_id (chỉ đọc).")
    ap.add_argument("--dsn", help="DSN Postgres (nên là role app_monitor); không bao giờ được in ra")
    ap.add_argument("--since", help="chỉ lấy lời gọi từ thời điểm này (ISO 8601, mặc định UTC nếu thiếu múi giờ)")
    ap.add_argument("--min-n", type=int, default=DEFAULT_MIN_N, help="dưới số mẫu này thì gắn cờ (n<…)")
    args = ap.parse_args(argv)
    if not args.dsn:
        print("LỖI: thiếu --dsn", file=sys.stderr)
        return 2
    try:
        since = _since(args.since) if args.since else None
    except ValueError:
        print("LỖI: --since phải là ngày/giờ ISO 8601", file=sys.stderr)
        return 2
    try:
        rep = summarize(fetch(args.dsn, since))
    except Exception as exc:  # noqa: BLE001 — chỉ in tên lớp: thông điệp của driver có thể chứa DSN
        print(f"LỖI: không đọc được llm_calls ({type(exc).__name__})", file=sys.stderr)
        return 2
    if not rep.groups:
        why = ", ".join(f"{k}={v}" for k, v in sorted(rep.excluded.items())) or "không có dòng nào"
        print(f"không có dòng sạch nào để tính tỉ số (loại: {why})", file=sys.stderr)
        return 1
    print(render(rep, args.min_n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
