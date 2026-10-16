"""Công cụ CHỈ ĐỌC cho phần thủ công của cổng 6 (phase6 mục 7, chặng 6D): (a) lấy mẫu lý do rủi ro cho người không xây M5 đọc;
(b) phân phối `raw_prob` để chọn `p_method`. Không đổi hành vi hệ thống.

Chạy: vỏ `scripts/sample_reasons.py`, `scripts/probe_p_distribution.py` (trên máy, `PYTHONPATH=backend`) hoặc trong container backend
(image không có `scripts/` — Q-6D-5 = A): `python -m app.audit.m5_review sample|probe …`.

- Dòng điểm log 4 = `check.POINT4_KEY` (một nguồn với `audit_check`; KHÁC định nghĩa của T29 `eval/predictions.py` — nhận cả
  `llm_layer_disabled`; ghi "Spec cần sửa (6D)"). Đọc qua `open_engine` (= `check.readonly_engine`, READ ONLY) + `check.load`.
- `sample`: stdout CHỈ là danh sách câu `reason` đánh số (+ 4 mẫu `[mẫu]` với `--templates`) — không `ticket_id`, `route`, mã luật ở
  trường riêng. Chữ `reason` giữ NGUYÊN VĂN (Q-6D-2 = C). `--key-out` ghi riêng file `so,ticket_id,decided_by,route` cho người đối chiếu.
  Mã thoát: 0 đủ n · 1 thiếu (stderr in số thật; thiếu câu llm chỉ báo stderr, Q-6D-1 = A) · 2 lỗi DB/ghi file (chỉ tên lớp lỗi).
- `probe`: `raw_prob` của dòng điểm 4 `decided_by="llm"`; bảng 10 bin + thanh `#`, 2 mức nhiều nhất + `share`, khuyến nghị
  (P6: `share > 0,60` → `sampling_k5`, bằng 0,60 → `self_report`, n < 20 → không đủ dữ liệu). `--csv` ghi `bin_lo,bin_hi,count`.
  Mã thoát (Q-6D-3 = A): 0 có khuyến nghị · 1 n < 20 · 2 lỗi DB/ghi file · 3 `LLM_BACKEND` khác `real` (kể cả chưa đặt, Q-6D-4 = A) —
  3 thắng 1; dòng cảnh báo là dòng ĐẦU stdout, vẫn in bảng. `LLM_BACKEND` là của tiến trình probe, không chắc trùng backend đã sinh dữ liệu.
- Không in DSN (chỉ nhãn role), không in `.env`, không in `detail` thô; không ghi file nào ngoài `--csv`/`--key-out` người dùng chỉ định.
"""

import argparse
import asyncio
import csv
import math
import random
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.check import POINT4_KEY, _since, load, readonly_engine
from app.domain.risk_factors import FactorCode
from app.risk.calibrator import Calibrator, CalibratorParams, FitInfo
from app.risk.estimator import PMethod, RiskEstimate
from app.risk.models import RuleVerdict
from app.risk.strategy import FullAutoBypass, decide
from app.settings import get_settings

MIN_N: Final = 20  # P6: n < 20 → không đủ dữ liệu
SHARE_THRESHOLD: Final = 0.60  # P6 [Chốt "> 60 %"]: bằng 60 % → self_report
BINS: Final = 10
BAR_MAX: Final = 50  # thanh `#` dài nhất; bin lớn hơn thì co tỉ lệ
SCRIPTED_WARNING: Final = "DỮ LIỆU GIẢ (ScriptedLLM) — không dùng để chọn p_method"
UNKNOWN_WARNING: Final = "KHÔNG RÕ NGUỒN DỮ LIỆU (LLM_BACKEND chưa đặt) — không dùng để chọn p_method"


@dataclass(frozen=True)
class Point4:
    """Một dòng điểm log 4. `route` từ `detail.route`; `decided_by` None = `full_auto` (Q-6-8)."""

    ticket_id: str
    decided_by: str | None
    route: str | None
    reason: str | None
    raw_prob: float | None
    p_method: str | None


@dataclass(frozen=True)
class Concentration:
    """`top` = (mức làm tròn 2 chữ số, số lần) của tối đa `top` mức nhiều nhất; `recommend` None = không đủ dữ liệu."""

    n: int
    top: tuple[tuple[float, int], ...]
    share: float
    recommend: PMethod | None


def point4_rows(by_ticket: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[Point4]:
    """THUẦN: dòng `POINT4_KEY` của mọi ticket, sắp theo `log_id` toàn cục (`check.load` chỉ sắp trong từng ticket)."""
    rows = sorted((r for rs in by_ticket.values() for r in rs if (r.get("step"), r.get("event")) == POINT4_KEY),
                  key=lambda r: r["log_id"])  # fmt: skip
    out = []
    for r in rows:
        detail = r.get("detail")
        route = detail.get("route") if isinstance(detail, Mapping) else None
        raw = r.get("raw_prob")
        out.append(Point4(ticket_id=r["ticket_id"], decided_by=r.get("decided_by"), route=route, reason=r.get("reason"),
                          raw_prob=None if raw is None else float(raw), p_method=r.get("p_method")))  # fmt: skip
    return out


def pick(rows: Sequence[Point4], *, n: int, seed: int, min_llm: int) -> list[Point4]:
    """P3: bỏ dòng không có `reason` hoặc `decided_by` ∉ {rule, llm}; bỏ trùng theo NGUYÊN VĂN `reason` (giữ dòng đứng trước); lấy
    `min(min_llm, #llm)` câu llm, phần còn lại từ luật, luật hết thì lấy nốt llm; xáo thứ tự cuối (vị trí không lộ llm/luật).
    Tất định theo `seed`. Thiếu → trả ít hơn `n` (người gọi báo số thật)."""
    if n < 1 or min_llm < 0:
        raise ValueError("n phải ≥ 1, min_llm phải ≥ 0")
    seen: set[str] = set()
    unique: list[Point4] = []
    for p in rows:
        if p.decided_by not in ("rule", "llm") or not p.reason:
            continue
        if p.reason in seen:
            continue
        seen.add(p.reason)
        unique.append(p)
    llm = [p for p in unique if p.decided_by == "llm"]
    rule = [p for p in unique if p.decided_by == "rule"]
    rng = random.Random(seed)
    chosen = rng.sample(llm, min(min_llm, len(llm), n))
    chosen += rng.sample(rule, min(n - len(chosen), len(rule)))
    rest = [p for p in llm if p not in chosen]
    chosen += rng.sample(rest, min(n - len(chosen), len(rest)))
    rng.shuffle(chosen)
    return chosen


def sample_reasons(rows: Sequence[Point4], *, n: int, seed: int, min_llm: int) -> list[str]:
    """P3: CHỈ chuỗi `reason` — không `ticket_id`, `route`, mã luật ở trường riêng."""
    return [p.reason or "" for p in pick(rows, n=n, seed=seed, min_llm=min_llm)]


# P4: số VÍ DỤ cố định (không phải ngưỡng/calibrator vận hành) — chữ do chính `strategy.decide` sinh. Calibrator Platt a=1, b=0 ≈ đồng nhất.
_EXAMPLE_THRESHOLDS: Final = (0.25, 0.75)
_EXAMPLE_CAL: Final = Calibrator(CalibratorParams(
    version="platt-20261015-00000000", method="platt", a=1.0, b=0.0,
    fitted_on=FitInfo(split="calibration", n=40, n_pos=10, n_families=8, data_sha256="0" * 64),
    created_at=datetime(2026, 10, 15, tzinfo=UTC),
))  # fmt: skip
_NO_MATCH: Final = RuleVerdict(matched=False, decision=None, rule_id=None, all_matched=[], description=None)
_ALLOW: Final = RuleVerdict(matched=True, decision="allow", rule_id="(mẫu)", all_matched=["(mẫu)"], description="mẫu")


def _example(raw: float, *factors: FactorCode) -> RiskEstimate:
    return RiskEstimate(raw_prob=raw, p_method="self_report", factors=factors, prompt_id="b14_risk_estimate",
                        prompt_version="mau", model="mau")  # fmt: skip


def template_reasons() -> list[str]:
    """4 mẫu của 5.3: đã hiệu chỉnh (AUTO) · chưa hiệu chỉnh (D-38, HITL) · hạ AUTO → HITL do `kb_gap` · `hybrid_guarded` + allow."""
    cases = [
        ("hybrid", _NO_MATCH, _example(0.10, FactorCode.ROUTINE_LOW_RISK), _EXAMPLE_CAL, False),
        ("hybrid", _NO_MATCH, _example(0.10, FactorCode.ROUTINE_LOW_RISK), None, False),
        ("hybrid", _NO_MATCH, _example(0.10, FactorCode.NO_POLICY_EVIDENCE), _EXAMPLE_CAL, True),
        ("hybrid_guarded", _ALLOW, _example(0.60, FactorCode.TARGET_IS_OTHER, FactorCode.SENSITIVE_DATA), _EXAMPLE_CAL, False),
    ]  # fmt: skip
    out: list[str] = []
    for strategy, verdict, estimate, calibrator, kb_gap in cases:
        d = decide(strategy, verdict, estimate, calibrator=calibrator, thresholds=_EXAMPLE_THRESHOLDS, kb_gap=kb_gap)  # type: ignore[arg-type]
        assert not isinstance(d, FullAutoBypass)
        out.append(d.reason)
    return out


def _checked(values: Iterable[float]) -> list[float]:
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, Real) or not 0.0 <= float(v) <= 1.0:  # NaN: so sánh luôn False
            raise ValueError("values: mọi giá trị phải là số thực trong đoạn [0, 1]")  # KHÔNG in giá trị
        out.append(float(v))
    return out


def concentration(values: Iterable[float], *, top: int = 2, threshold: float = SHARE_THRESHOLD) -> Concentration:
    """P6: làm tròn 2 chữ số, đếm tần suất; `share` = tổng `top` mức nhiều nhất / n; `> threshold` → `sampling_k5`, còn lại
    `self_report`; n < 20 → None."""
    levels = Counter(round(v, 2) for v in _checked(values))
    n = sum(levels.values())
    best = tuple(sorted(levels.items(), key=lambda kv: (-kv[1], kv[0]))[:top])
    share = sum(c for _, c in best) / n if n else 0.0
    recommend: PMethod | None = None
    if n >= MIN_N:
        recommend = "sampling_k5" if share > threshold else "self_report"
    return Concentration(n=n, top=best, share=share, recommend=recommend)


def histogram(values: Iterable[float]) -> list[tuple[float, float, int]]:
    """10 bin [0,0–0,1) … [0,9–1,0]; 1,0 vào bin cuối."""
    counts = [0] * BINS
    for v in _checked(values):
        counts[min(math.floor(round(v * BINS, 9)), BINS - 1)] += 1
    return [(round(i / BINS, 1), round((i + 1) / BINS, 1), c) for i, c in enumerate(counts)]


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def probe_report(values: Sequence[float], *, llm_backend: str | None) -> tuple[str, int]:
    """(văn bản, mã thoát) — P7 + Q-6D-3/4. Cảnh báo dữ liệu không thật là dòng ĐẦU; vẫn in bảng."""
    conc = concentration(values)
    lines = []
    if llm_backend != "real":
        lines.append(SCRIPTED_WARNING if llm_backend == "scripted" else UNKNOWN_WARNING)
    bins = histogram(values)
    widest = max(c for *_, c in bins)
    scale = BAR_MAX / widest if widest > BAR_MAX else 1.0
    lines.append(f"probe_p_distribution: n = {conc.n} (dòng điểm 4 decided_by=llm có raw_prob)")
    lines += [f"{_num(lo)[:-1]}–{_num(hi)[:-1]} | {c:>4} | {'#' * math.ceil(c * scale)}".rstrip() for lo, hi, c in bins]
    if conc.top:
        top = ", ".join(f"{_num(level)} ({count})" for level, count in conc.top)
        lines.append(f"{len(conc.top)} mức nhiều nhất: {top} — share {_num(conc.share)}")
    if conc.recommend is None:
        lines.append(f"khuyến nghị p_method: không đủ dữ liệu (n < {MIN_N})")
    else:
        lines.append(f"khuyến nghị p_method: {conc.recommend} (share {'>' if conc.share > SHARE_THRESHOLD else '≤'} {_num(SHARE_THRESHOLD)})")
    code = 3 if llm_backend != "real" else (1 if conc.recommend is None else 0)
    return "\n".join(lines), code


def open_engine(dsn: str) -> AsyncEngine:
    """Đường DUY NHẤT hai vỏ mở DB: mọi giao dịch READ ONLY (P8, M-6D-6)."""
    return readonly_engine(dsn)


async def load_point4(engine: AsyncEngine, since: datetime) -> list[Point4]:
    by_ticket, _ = await load(engine, since=since)
    return point4_rows(by_ticket)


async def _fetch(dsn: str, since: datetime) -> list[Point4]:
    engine = open_engine(dsn)
    try:
        return await load_point4(engine, since)
    finally:
        await engine.dispose()


def _rows_from_db(prog: str, since: datetime) -> list[Point4] | None:
    """Nhãn role ra stderr — KHÔNG in DSN; lỗi DB: chỉ tên lớp (thông điệp driver có thể mang host/role). None = lỗi."""
    settings = get_settings()
    role = "app_monitor" if settings.monitor_database_url else "app_rw"
    dsn = settings.monitor_database_url or settings.database_url
    print(f"{prog}: nguồn {role} (READ ONLY)", file=sys.stderr)
    try:
        return asyncio.run(_fetch(dsn, since))
    except Exception as exc:  # noqa: BLE001
        print(f"{prog}: không đọc được DB ({type(exc).__name__})", file=sys.stderr)
        return None


def _write_csv(prog: str, path: str, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> bool:
    try:
        with Path(path).open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
    except OSError as exc:
        print(f"{prog}: không ghi được file ({type(exc).__name__})", file=sys.stderr)
        return False
    return True


def _one_line(text: str) -> str:
    return " ".join(text.split())


def sample_main(argv: Sequence[str] | None = None) -> int:
    prog = "sample_reasons"
    parser = argparse.ArgumentParser(prog=prog, description="Lấy mẫu lý do rủi ro (điểm log 4) cho người đọc — chỉ đọc.")
    parser.add_argument("--since", type=_since, required=True, help="ticket có dòng audit từ thời điểm này (ISO, có múi giờ)")
    parser.add_argument("--n", type=int, default=10, help="số câu (mặc định 10)")
    parser.add_argument("--seed", type=int, required=True, help="hạt ngẫu nhiên (ghi lại để lặp lại được)")
    parser.add_argument("--min-llm", type=int, default=3, help="cố gắng ít nhất bấy nhiêu câu decided_by=llm (mặc định 3)")
    parser.add_argument("--templates", action="store_true", help="in thêm 4 mẫu reason của strategy (đánh dấu [mẫu])")
    parser.add_argument("--key-out", help="file đối chiếu số → ticket_id, decided_by, route (KHÔNG đưa người đọc)")
    args = parser.parse_args(argv)
    if args.n < 1 or args.min_llm < 0:
        parser.error("--n phải ≥ 1, --min-llm phải ≥ 0")
    rows = _rows_from_db(prog, args.since)
    if rows is None:
        return 2
    picked = pick(rows, n=args.n, seed=args.seed, min_llm=args.min_llm)
    if args.key_out is not None:
        key = ((i, p.ticket_id, p.decided_by or "", p.route or "") for i, p in enumerate(picked, 1))
        if not _write_csv(prog, args.key_out, ("so", "ticket_id", "decided_by", "route"), key):
            return 2
    lines = [f"{i}. {_one_line(p.reason or '')}" for i, p in enumerate(picked, 1)]
    if args.templates:
        lines += [f"{i}. [mẫu] {_one_line(r)}" for i, r in enumerate(template_reasons(), len(picked) + 1)]
    print("\n".join(lines))
    n_llm = sum(p.decided_by == "llm" for p in picked)
    print(f"{prog}: lấy được {len(picked)}/{args.n} câu khác nhau", file=sys.stderr)
    if n_llm < args.min_llm:
        print(f"{prog}: thiếu câu llm: {n_llm}/{args.min_llm}", file=sys.stderr)
    return 0 if len(picked) == args.n else 1


def probe_main(argv: Sequence[str] | None = None) -> int:
    prog = "probe_p_distribution"
    parser = argparse.ArgumentParser(prog=prog, description="Phân phối raw_prob (điểm log 4, decided_by=llm) — chỉ đọc.")
    parser.add_argument("--since", type=_since, required=True, help="ticket có dòng audit từ thời điểm này (ISO, có múi giờ)")
    parser.add_argument("--csv", help="ghi histogram bin_lo,bin_hi,count ra file này")
    args = parser.parse_args(argv)
    rows = _rows_from_db(prog, args.since)
    if rows is None:
        return 2
    values = [p.raw_prob for p in rows if p.decided_by == "llm" and p.raw_prob is not None]
    text, code = probe_report(values, llm_backend=get_settings().llm_backend)
    if args.csv is not None:
        bins = ((f"{lo:.1f}", f"{hi:.1f}", c) for lo, hi, c in histogram(values))
        if not _write_csv(prog, args.csv, ("bin_lo", "bin_hi", "count"), bins):
            return 2
    print(text)
    return code


def _dispatch(argv: Sequence[str]) -> int:
    """`python -m app.audit.m5_review sample|probe …` (Q-6D-5 = A)."""
    commands = {"sample": sample_main, "probe": probe_main}
    if not argv or argv[0] not in commands:
        print("dùng: python -m app.audit.m5_review sample|probe …", file=sys.stderr)
        return 2
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(_dispatch(sys.argv[1:]))
