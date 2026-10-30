"""Báo cáo RQ2 từ `collected.jsonl` (offline, không DB, không mạng): hiệu chỉnh kiểm tra chéo, chỉ số 3 cách × trước/sau, CSV từng lá,
bảng, reliability diagram.

- Phạm vi `common`: lá có p thô VÀ p hiệu chỉnh của MỌI cách có mặt trong run (so cùng một tập); `own`: mọi lá có p của cách đó.
- (c) không khả thi / không chạy → không có cột `p_c_*`, không có dòng (c) trong bảng (không làm giả số).
- PNG: repo không có matplotlib/pillow (thêm phải sửa `pyproject.toml` — file trong tag), nên PNG vẽ bằng thư viện chuẩn (zlib): cột tỉ lệ
  dương theo 10 ngăn đều, chấm p̄ của ngăn, đường chéo; KHÔNG có chữ. Bản SVG cùng tên có nhãn trục và số lá từng ngăn.
"""

import csv
import io
import json
import math
import struct
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from app.eval.rq2.calib import CalRow, FoldInfo, cross_fit
from app.eval.rq2.filestore import write_atomic
from app.eval.rq2.metrics import (
    N_BOOT,
    STATS,
    Bin,
    Point,
    bootstrap,
    reliability_bins,
    resolution,
)
from app.eval.stats import SEED

type Method = Literal["a", "b", "c"]
type Stage = Literal["raw", "cal"]
METHODS: Final[tuple[Method, ...]] = ("a", "b", "c")
STAGES: Final[tuple[Stage, ...]] = ("raw", "cal")
METHOD_NAMES: Final[dict[Method, str]] = {"a": "self_report", "b": "sampling_k5", "c": "token_logprob"}
BOOT_NOTE: Final = "n_boot = 1000 theo đặc tả Phase 11; P8 §6.4 / stats.BOOTSTRAP_N dùng 2000"

# (c) — câu trạng thái khả thi theo tên model B14 (llm_calls.model của S1), ĐP 30/10 16:50
C_PROBED_MODEL: Final = "deepseek-flash"
C_PROBE_FILE: Final = ".verify/rq2/logprobs-thu-3010.txt"
C_PROBE_SHA256: Final = "9936e71c03906c841c9d33787b6fb0fe075f46402a3fb0fec243db833b317600"


def c_feasibility_note(model: str) -> str:
    if model == C_PROBED_MODEL:
        return (f"(c) khả thi: lời gọi thử 30/10 trả logprobs (file {C_PROBE_FILE} ngoài repo, sha256 {C_PROBE_SHA256})")
    return (f"đã thấy logprobs trên {C_PROBED_MODEL}, CHƯA kiểm trên model B14 ({model}) — Quân kiểm bằng hàm kiểm khả thi khi chạy "
            "D1 31/10")  # fmt: skip


def methods_present(rows: Sequence[Mapping[str, Any]]) -> list[Method]:
    """(a), (b) luôn có cột; (c) chỉ khi bản thu thập có khoá `p_c` (khả thi)."""
    return [m for m in METHODS if m != "c" or any("p_c" in r for r in rows)]


def calibrate_all(
    rows: Sequence[Mapping[str, Any]], methods: Sequence[Method], *, now: datetime
) -> tuple[dict[Method, dict[str, float | None]], dict[Method, list[FoldInfo]]]:
    cal_rows = [CalRow(r["ticket_id"], r["family"], int(r["fold"]), bool(r["y"])) for r in rows]
    by_id = {r["ticket_id"]: r for r in rows}
    cal: dict[Method, dict[str, float | None]] = {}
    infos: dict[Method, list[FoldInfo]] = {}
    for m in methods:
        cal[m], infos[m] = cross_fit(cal_rows, _raw_of(by_id, m), now=now)
    return cal, infos


def _raw_of(by_id: Mapping[str, Mapping[str, Any]], m: Method) -> Callable[[CalRow], float | None]:
    def raw(cr: CalRow) -> float | None:
        v = by_id[cr.ticket_id].get(f"p_{m}")
        return None if v is None else float(v)

    return raw


def _value(row: Mapping[str, Any], cal: Mapping[Method, Mapping[str, float | None]], m: Method, stage: Stage) -> float | None:
    if stage == "raw":
        v = row.get(f"p_{m}")
        return None if v is None else float(v)
    return cal[m].get(row["ticket_id"])


def points(rows: Sequence[Mapping[str, Any]], cal: Mapping[Method, Mapping[str, float | None]], m: Method, stage: Stage,
           ids: set[str] | None = None) -> list[Point]:  # fmt: skip
    out = []
    for r in rows:
        if ids is not None and r["ticket_id"] not in ids:
            continue
        v = _value(r, cal, m, stage)
        if v is not None:
            out.append(Point(r["ticket_id"], r["family"], v, bool(r["y"])))
    return out


def common_ids(rows: Sequence[Mapping[str, Any]], cal: Mapping[Method, Mapping[str, float | None]], methods: Sequence[Method]) -> set[str]:
    return {r["ticket_id"] for r in rows if all(_value(r, cal, m, s) is not None for m in methods for s in STAGES)}


def _ci(ci: Any) -> dict[str, Any]:
    return {"point": ci.point, "lo": ci.lo, "hi": ci.hi, "n_used": ci.n_used, "n_undefined": ci.n_undefined}


def metric_rows(
    rows: Sequence[Mapping[str, Any]], cal: Mapping[Method, Mapping[str, float | None]], methods: Sequence[Method], *,
    n_boot: int = N_BOOT, seed: int = SEED,
) -> list[dict[str, Any]]:  # fmt: skip
    common = common_ids(rows, cal, methods)
    out = []
    for scope in ("common", "own"):
        for m in methods:
            for stage in STAGES:
                pts = points(rows, cal, m, stage, common if scope == "common" else None)
                entry: dict[str, Any] = {"method": m, "p_method": METHOD_NAMES[m], "stage": stage, "scope": scope, "n": len(pts),
                                         "n_families": len({q.family for q in pts})}  # fmt: skip
                if pts:
                    res = resolution([q.p for q in pts])
                    entry.update({"n_levels": res.n_levels, "top2_share": res.top2_share, "levels": res.levels})
                    for name, stat in STATS.items():
                        entry[name] = _ci(bootstrap(pts, stat, n_boot=n_boot, seed=seed))
                out.append(entry)
    return out


def _fmt(x: float | None, nd: int = 4) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def table_md(metrics: Sequence[Mapping[str, Any]]) -> str:
    head = ("| cách | p_method | giai đoạn | phạm vi | n | số họ | ECE 10 ngăn đều [KTC 95%] | ECE 5 ngăn cùng số mẫu [KTC 95%] | "
            "Brier [KTC 95%] | số mức p | tỉ lệ 2 mức đông nhất |")  # fmt: skip
    lines = [head, "|" + "---|" * 11]
    for e in metrics:
        cells = [e["method"], e["p_method"], "trước" if e["stage"] == "raw" else "sau", e["scope"], str(e["n"]), str(e["n_families"])]
        for name in STATS:
            ci = e.get(name)
            cells.append("—" if ci is None else f"{_fmt(ci['point'])} [{_fmt(ci['lo'])}; {_fmt(ci['hi'])}]")
        cells += [str(e.get("n_levels", "—")), _fmt(e.get("top2_share"), 3) if "top2_share" in e else "—"]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def per_ticket_csv(rows: Sequence[Mapping[str, Any]], cal: Mapping[Method, Mapping[str, float | None]], methods: Sequence[Method]) -> str:
    cols = ["ticket_id", "scenario_id", "family", "fold", "y"] + [f"p_{m}_{s}" for m in methods for s in STAGES]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in sorted(rows, key=lambda r: r["ticket_id"]):
        vals = [_value(r, cal, m, s) for m in methods for s in STAGES]
        w.writerow([r["ticket_id"], r["scenario_id"], r["family"], r["fold"], int(bool(r["y"]))] +
                   ["" if v is None else repr(v) for v in vals])  # fmt: skip
    return buf.getvalue()


# ---- reliability diagram -------------------------------------------------------------------------------------------------------

SIZE: Final = 400
PAD: Final = 40
_WHITE, _GRID, _AXIS, _DIAG, _BAR, _DOT = (255, 255, 255), (230, 230, 230), (0, 0, 0), (150, 150, 150), (110, 150, 210), (20, 40, 90)


def png_bytes(width: int, height: int, pixels: Sequence[bytearray]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def reliability_png(bins: Sequence[Bin]) -> bytes:
    px = [bytearray(_WHITE * SIZE) for _ in range(SIZE)]
    span = SIZE - 2 * PAD

    def put(x: int, y: int, c: tuple[int, int, int]) -> None:
        if 0 <= x < SIZE and 0 <= y < SIZE:
            px[y][3 * x : 3 * x + 3] = bytes(c)

    def to_px(u: float, v: float) -> tuple[int, int]:
        return PAD + round(u * span), SIZE - PAD - round(v * span)

    for i in range(11):
        for t in range(span + 1):
            put(PAD + round(i * span / 10), SIZE - PAD - t, _GRID)
            put(PAD + t, SIZE - PAD - round(i * span / 10), _GRID)
    for b in bins:
        if b.frac_pos is None:
            continue
        x0, y0 = to_px(b.lo, 0)
        x1, y1 = to_px(b.hi, b.frac_pos)
        for x in range(x0 + 2, x1 - 1):
            for y in range(y1, y0):
                put(x, y, _BAR)
    for t in range(span + 1):
        put(PAD + t, SIZE - PAD - t, _DIAG)
        put(PAD, SIZE - PAD - t, _AXIS)
        put(PAD + t, SIZE - PAD, _AXIS)
    for b in bins:
        if b.mean_p is None or b.frac_pos is None:
            continue
        cx, cy = to_px(b.mean_p, b.frac_pos)
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                put(cx + dx, cy + dy, _DOT)
    return png_bytes(SIZE, SIZE, px)


def reliability_svg(bins: Sequence[Bin], title: str) -> str:
    span = SIZE - 2 * PAD
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">',
             f'<rect width="{SIZE}" height="{SIZE}" fill="#fff"/>',
             f'<text x="{SIZE / 2}" y="20" text-anchor="middle" font-size="13">{title}</text>',
             f'<line x1="{PAD}" y1="{SIZE - PAD}" x2="{SIZE - PAD}" y2="{PAD}" stroke="#999" stroke-dasharray="4"/>']  # fmt: skip
    for b in bins:
        x = PAD + b.lo * span
        if b.frac_pos is not None:
            h = b.frac_pos * span
            parts.append(f'<rect x="{x + 2:.1f}" y="{SIZE - PAD - h:.1f}" width="{span / 10 - 4:.1f}" height="{h:.1f}" fill="#6e96d2"/>')
        parts.append(f'<text x="{x + span / 20:.1f}" y="{SIZE - PAD + 14}" text-anchor="middle" font-size="9">{b.n}</text>')
        if b.mean_p is not None and b.frac_pos is not None:
            parts.append(f'<circle cx="{PAD + b.mean_p * span:.1f}" cy="{SIZE - PAD - b.frac_pos * span:.1f}" r="3" fill="#14285a"/>')
    parts += [f'<line x1="{PAD}" y1="{SIZE - PAD}" x2="{SIZE - PAD}" y2="{SIZE - PAD}" stroke="#000"/>',
              f'<line x1="{PAD}" y1="{SIZE - PAD}" x2="{PAD}" y2="{PAD}" stroke="#000"/>',
              f'<text x="{SIZE / 2}" y="{SIZE - 8}" text-anchor="middle" font-size="11">p (10 ngăn đều; số dưới trục = số lá)</text>',
              (f'<text x="12" y="{SIZE / 2}" text-anchor="middle" font-size="11" transform="rotate(-90 12 {SIZE / 2})">'
               'tỉ lệ cần người (y=1)</text>'), "</svg>"]  # fmt: skip
    return "\n".join(parts) + "\n"


# ---- B5 (chỉ mô tả độ phân giải (a)) ---------------------------------------------------------------------------------------------


def _floats(values: Sequence[str]) -> list[float] | None:
    out = []
    for v in values:
        try:
            x = float(v)
        except ValueError:
            return None
        if not (math.isfinite(x) and 0.0 <= x <= 1.0):
            return None
        out.append(x)
    return out


def describe_b5(paths: Sequence[Path], column: str | None = None) -> list[dict[str, Any]]:
    """Mỗi file CSV một mục (tên file, không đường dẫn). Cột: `column`, hoặc cột DUY NHẤT mà mọi ô khác rỗng là số trong [0, 1]."""
    out = []
    for i, path in enumerate(paths):
        rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
        if not rows:
            raise ValueError(f"B5 file #{i + 1}: rỗng")
        names = [column] if column is not None else [c for c in rows[0] if _floats([r[c] for r in rows if (r[c] or "").strip()])]
        if len(names) != 1 or names[0] not in rows[0]:
            raise ValueError(f"B5 file #{i + 1}: không xác định được cột giá trị — truyền --b5-col")
        vals = _floats([r[names[0]] for r in rows if (r[names[0]] or "").strip()])
        if not vals:
            raise ValueError(f"B5 file #{i + 1}: cột giá trị không phải số trong [0, 1]")
        res = resolution(vals)
        out.append({"file": path.name, "column": names[0], **asdict(res)})
    return out


# ---- ghi thư mục run ------------------------------------------------------------------------------------------------------------


def write_report(
    run_dir: Path, rows: Sequence[Mapping[str, Any]], collect_manifest: Mapping[str, Any], *, now: datetime,
    b5: list[dict[str, Any]] | None = None, n_boot: int = N_BOOT, seed: int = SEED,
) -> dict[str, Any]:  # fmt: skip
    methods = methods_present(rows)
    cal, infos = calibrate_all(rows, methods, now=now)
    metrics = metric_rows(rows, cal, methods, n_boot=n_boot, seed=seed)
    write_atomic(run_dir / "per_ticket.csv", per_ticket_csv(rows, cal, methods))
    write_atomic(run_dir / "tables.md", table_md(metrics))
    write_atomic(run_dir / "metrics.json", json.dumps(metrics, ensure_ascii=False, indent=1, sort_keys=True))
    figures = []
    for m in methods:
        for stage in STAGES:
            bins = reliability_bins(points(rows, cal, m, stage))
            name = f"reliability_{m}_{stage}"
            (run_dir / f"{name}.png").write_bytes(reliability_png(bins))
            label = f"({m}) {METHOD_NAMES[m]} — {'trước' if stage == 'raw' else 'sau'} hiệu chỉnh"
            write_atomic(run_dir / f"{name}.svg", reliability_svg(bins, label))
            figures.append(name)
    model = collect_manifest.get("model")
    manifest = {
        **collect_manifest,
        "report": {
            "created_at": now.isoformat(), "methods": methods, "n_boot": n_boot, "bootstrap_note": BOOT_NOTE, "seed": seed,
            "bootstrap_unit": "family", "level": 0.95, "calibrator": "platt (app.risk.calibrator.fit_platt)",
            "label": "y = expected_route != AUTO (app/eval/calibrate.py:184)", "cv": "5 phần theo họ (eval/folds.csv)",
            "folds": {m: [f.to_dict() for f in infos[m]] for m in methods},
            "ece": {"ece10": "10 ngăn đều (decision_math.ece)", "ece5_mass": "5 ngăn cùng số mẫu, sắp (p, ticket_id)"},
            "figures": figures, "b5": b5,
            "c_feasibility_note": c_feasibility_note(model) if isinstance(model, str) else None,
        },
    }  # fmt: skip
    write_atomic(run_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
    return manifest
