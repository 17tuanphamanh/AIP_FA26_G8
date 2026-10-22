"""G10 — ba biến thể xác suất thô của lớp LLM ở M5, ghi `probs.jsonl` (P8 v1.4 §5.4 "Biến thể xác suất (offline, script)", §5.6).

  PYTHONPATH=backend uv run python scripts/eval/prob_variants.py build   WITH.jsonl WITHOUT.jsonl OUT/probs.jsonl
  PYTHONPATH=backend uv run python scripts/eval/prob_variants.py compare WITH.jsonl OUT/probs.jsonl [--json OUT/so-sanh.json]

Ba biến thể (`variant` trong file):
- `with_evidence`  — xác suất thô đã ghi ở điểm log 4 của lượt chạy trên stack (S1: ca không khớp luật; S2: mọi ca có hành động).
                     Chép nguyên, không tính lại.
- `no_evidence`    — `estimator.estimate(action, ctx, [])`: một lần gọi B14 mới, trích đoạn rỗng.
- `max`            — `max(with_evidence, no_evidence)` của cùng ca, trên xác suất THÔ (trước hiệu chỉnh); chỉ khi có đủ hai biến thể.

`kb_gap` là thuộc tính của ca (bằng chứng gốc ở stack), KHÔNG của biến thể. `probs.jsonl` không có cột `kb_gap` (hợp đồng §5.6: đúng 3
trường `scenario_id`, `variant`, `raw_prob`); bên dùng đọc `kb_gap` từ bản ghi stack theo `scenario_id`. Ca có `kb_gap` ở stack đã
gửi B14 trích đoạn rỗng sẵn (D-34) → `no_evidence` CHÉP `raw_prob` của `with_evidence`, không gọi lại (số ca chép được in ra).
Mỗi lượt (S1, S2) một file `probs.jsonl` riêng, phân biệt bằng đường dẫn. Chỉ ca đi lớp LLM mới có dòng.

Đầu vào (định dạng giả định, JSONL một đối tượng một dòng, không trường lạ):
- WITH.jsonl    `{scenario_id, family, split: "calibration"|"test", gold_route, raw_prob, kb_gap}` — mỗi ca đi lớp LLM của lượt đó.
- WITHOUT.jsonl `{scenario_id, raw_prob}` hoặc `{scenario_id, error}` — kết quả `collect_no_evidence`; ca `kb_gap` không có dòng.
- cases.jsonl   `{scenario_id, action, ctx}` (Action, RiskContext tuần tự hóa) — đầu vào của `collect_no_evidence`.

Thu thập `no_evidence` gọi LLM thật → thuộc mốc G, không có subcommand ở đây (cần nối gateway). Ở mốc G:
  rows = asyncio.run(collect_no_evidence(LlmRiskEstimator(llm, p_method=<như bản đóng băng>, eval_mode=True), recorded, cases))
  write_jsonl(path, rows)
Lần gọi lỗi (`LLMUnavailable`, `LLMSchemaError`, `LLMBudgetExceeded`, `TurnBudgetExceeded`) → dòng `error` (tên lớp lỗi), ca đó bị bỏ
`no_evidence` + `max`, không fail cả lượt. Lỗi khác là bug → ném lên.

`compare` (chẩn đoán, KHÔNG chọn biến thể): mỗi biến thể fit Platt (`app.risk.calibrator.fit_platt`) CHỈ trên mẫu `split="calibration"`,
đo ECE/Brier/AUC (`app.risk.decision_math`) trên `split="test"`; gồm cả phạm vi "own" (mọi ca có biến thể đó) lẫn "common" (ca có đủ cả
ba biến thể). Chọn biến thể theo chi phí là việc của `fit_fold` (calibrate.py, chưa có) và không nhìn phần đo (P8 §5.3).
Không gọi mạng, không đọc `.env`, không đọc kịch bản/KB.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from app.core.errors import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.core.turn_budget import TurnBudgetExceeded
from app.domain.action import Action
from app.risk.calibrator import Calibrator, LabeledSample, fit_platt
from app.risk.decision_math import Route, auc, brier, ece
from app.risk.estimator import RiskEstimator
from app.risk.models import RiskContext
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

type Variant = Literal["with_evidence", "no_evidence", "max"]
VARIANTS: tuple[Variant, ...] = ("with_evidence", "no_evidence", "max")
RECOVERABLE = (LLMUnavailable, LLMSchemaError, LLMBudgetExceeded, TurnBudgetExceeded)

Prob = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
Id = Annotated[str, Field(min_length=1)]


class DataError(ValueError):
    """Dữ liệu đầu vào sai — thông điệp nêu vị trí/loại lỗi, KHÔNG in giá trị."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)


class RecordedCase(_Strict):
    scenario_id: Id
    family: Id
    split: Literal["calibration", "test"]
    gold_route: Route
    raw_prob: Prob
    kb_gap: bool


class CollectCase(BaseModel):
    """Lax (không `strict`): `action`/`ctx` đi vào từ JSON (datetime chuỗi, mapping → model)."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    scenario_id: Id
    action: Action
    ctx: RiskContext


class WithoutRow(_Strict):
    scenario_id: Id
    raw_prob: Prob | None = None
    error: Id | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "WithoutRow":
        if (self.raw_prob is None) == (self.error is None):
            raise ValueError("phải có đúng một trong raw_prob, error")
        return self


class ProbRow(_Strict):
    """Hợp đồng `probs.jsonl` (P8 §5.6): đúng 3 trường, theo thứ tự này."""

    scenario_id: Id
    variant: Variant
    raw_prob: Prob


# ---- đọc/ghi -----------------------------------------------------------------------------------------------------------


def _where(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in err['loc']) or '(dòng)'}: {err['type']}" for err in e.errors())


def load_jsonl[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise DataError(f"{path.name}: file rỗng")
    out: list[M] = []
    for i, line in enumerate(lines, 1):
        if not line.strip():
            raise DataError(f"{path.name}:{i}: dòng trống")
        try:
            out.append(model.model_validate_json(line))
        except ValidationError as e:
            raise DataError(f"{path.name}:{i}: {_where(e)}") from None
    return out


def write_jsonl(path: Path, rows: Sequence[BaseModel]) -> None:
    """Tạo file mới (`x`): không ghi đè. Một dòng một đối tượng, thứ tự trường theo model, `\\n` cuối file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")


def _unique(ids: Sequence[str], what: str) -> None:
    dup = [k for k, n in Counter(ids).items() if n > 1]
    if dup:
        raise DataError(f"{what}: {len(dup)} scenario_id trùng")


# ---- thu thập no_evidence (mốc G; test bằng LLM giả) --------------------------------------------------------------------


async def collect_no_evidence(
    estimator: RiskEstimator, recorded: Sequence[RecordedCase], cases: Mapping[str, CollectCase]
) -> list[WithoutRow]:
    """Gọi `estimator.estimate(action, ctx, [])` cho mọi ca KHÔNG có `kb_gap` (ca `kb_gap` chép ở `build_probs`, không gọi lại).
    Tuần tự, theo thứ tự `recorded`. Thiếu đầu vào của ca nào → `DataError` TRƯỚC khi gọi (không tốn lời gọi)."""
    _unique([r.scenario_id for r in recorded], "recorded")
    todo = [r for r in recorded if not r.kb_gap]
    missing = [r.scenario_id for r in todo if r.scenario_id not in cases]
    if missing:
        raise DataError(f"cases: thiếu đầu vào của {len(missing)} ca (đầu tiên: {missing[0]})")
    out: list[WithoutRow] = []
    for r in todo:
        case = cases[r.scenario_id]
        try:
            est = await estimator.estimate(case.action, case.ctx, [])
        except RECOVERABLE as e:
            out.append(WithoutRow(scenario_id=r.scenario_id, error=type(e).__name__))
            continue
        out.append(WithoutRow(scenario_id=r.scenario_id, raw_prob=est.raw_prob))
    return out


# ---- ghép biến thể -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildResult:
    rows: list[ProbRow]
    n_cases: int
    n_copied: int  # no_evidence chép từ with_evidence vì kb_gap
    failed: dict[str, int]  # tên lớp lỗi → số ca bị bỏ no_evidence + max
    n_missing: int  # ca không kb_gap mà không có dòng WITHOUT → bỏ no_evidence + max


def build_probs(recorded: Sequence[RecordedCase], without: Sequence[WithoutRow]) -> BuildResult:
    _unique([r.scenario_id for r in recorded], "recorded")
    _unique([w.scenario_id for w in without], "without")
    known = {r.scenario_id: r for r in recorded}
    unknown = [w.scenario_id for w in without if w.scenario_id not in known]
    if unknown:
        raise DataError(f"without: {len(unknown)} scenario_id không có trong recorded")
    by_id = {w.scenario_id: w for w in without}
    called_kb_gap = [s for s in by_id if known[s].kb_gap]
    if called_kb_gap:
        raise DataError(f"without: {len(called_kb_gap)} ca có kb_gap bị gọi lại (phải chép, không gọi)")
    rows: list[ProbRow] = []
    copied = missing = 0
    failed: Counter[str] = Counter()
    for r in sorted(recorded, key=lambda c: c.scenario_id):
        rows.append(ProbRow(scenario_id=r.scenario_id, variant="with_evidence", raw_prob=r.raw_prob))
        if r.kb_gap:
            no = r.raw_prob
            copied += 1
        else:
            w = by_id.get(r.scenario_id)
            if w is None:
                missing += 1
                continue
            if w.error is not None or w.raw_prob is None:
                failed[w.error or "?"] += 1
                continue
            no = w.raw_prob
        rows.append(ProbRow(scenario_id=r.scenario_id, variant="no_evidence", raw_prob=no))
        rows.append(ProbRow(scenario_id=r.scenario_id, variant="max", raw_prob=max(r.raw_prob, no)))
    return BuildResult(rows, len(recorded), copied, dict(sorted(failed.items())), missing)


# ---- so sánh (chẩn đoán) -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VariantReport:
    variant: Variant
    scope: Literal["own", "common"]
    n_cal: int
    n_cal_pos: int
    n_test: int
    n_test_pos: int
    fit: str  # "ok" hoặc lý do không fit được (không hiệu chỉnh)
    calibrator_version: str | None
    raw_ece: float | None
    raw_brier: float | None
    cal_ece: float | None
    cal_brier: float | None
    cal_auc: float | None


def fit_variant(samples: Sequence[LabeledSample], *, now: datetime) -> Calibrator | str:
    """Platt trên `samples` NGUYÊN VẸN — `fit_platt` ném `LeakageError` nếu có mẫu ngoài split calibration (không nuốt). Fit lỗi
    (n < 10, một lớp, a ≤ 0…) → trả lý do."""
    try:
        return fit_platt(samples, now=now)
    except ValueError as e:
        return str(e)


def _report(variant: Variant, scope: Literal["own", "common"], samples: list[LabeledSample], now: datetime) -> VariantReport:
    cal = [s for s in samples if s.split == "calibration"]
    test = [s for s in samples if s.split == "test"]
    fitted = fit_variant(cal, now=now) if cal else "không có mẫu calibration"
    raw_ece = raw_brier = cal_ece = cal_brier = cal_auc = None
    if test:
        raw = [s.raw_prob for s in test]
        y = [s.y for s in test]
        raw_ece, raw_brier = ece(raw, y), brier(raw, y)
        if isinstance(fitted, Calibrator):
            p = [fitted.transform(x) for x in raw]
            cal_ece, cal_brier = ece(p, y), brier(p, y)
            try:
                cal_auc = auc(p, y)
            except ValueError:  # phần đo chỉ một lớp: AUC không xác định
                cal_auc = None
    return VariantReport(
        variant, scope, len(cal), sum(s.y for s in cal), len(test), sum(s.y for s in test),
        "ok" if isinstance(fitted, Calibrator) else fitted,
        fitted.params.version if isinstance(fitted, Calibrator) else None,
        raw_ece, raw_brier, cal_ece, cal_brier, cal_auc,
    )  # fmt: skip


def compare_variants(recorded: Sequence[RecordedCase], rows: Sequence[ProbRow], *, now: datetime) -> list[VariantReport]:
    """Không trả "biến thể tốt nhất": số đo trên phần đo chỉ để báo cáo, không để chọn (P8 §5.3)."""
    _unique([r.scenario_id for r in recorded], "recorded")
    meta = {r.scenario_id: r for r in recorded}
    by_variant: dict[Variant, dict[str, float]] = {v: {} for v in VARIANTS}
    for row in rows:
        if row.scenario_id not in meta:
            raise DataError("probs: có scenario_id không nằm trong recorded")
        if row.scenario_id in by_variant[row.variant]:
            raise DataError("probs: trùng (scenario_id, variant)")
        by_variant[row.variant][row.scenario_id] = row.raw_prob
    common = set.intersection(*(set(d) for d in by_variant.values()))
    out: list[VariantReport] = []
    for scope in ("own", "common"):
        for v in VARIANTS:
            ids = sorted(by_variant[v] if scope == "own" else common & set(by_variant[v]))
            samples = [
                LabeledSample(split=meta[i].split, family=meta[i].family, raw_prob=by_variant[v][i],
                              y=meta[i].gold_route != "AUTO")
                for i in ids
            ]  # fmt: skip
            out.append(_report(v, scope, samples, now))
    return out


def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.4f}"


def format_table(reports: Sequence[VariantReport]) -> str:
    head = f"{'phạm vi':8} {'biến thể':14} {'n_cal':>6} {'n_test':>6} {'ECE thô':>8} {'Brier thô':>9} {'ECE hc':>8} {'Brier hc':>9} {'AUC hc':>7}  fit"
    lines = [head]
    for r in reports:
        lines.append(
            f"{r.scope:8} {r.variant:14} {r.n_cal:6d} {r.n_test:6d} {_fmt(r.raw_ece):>8} {_fmt(r.raw_brier):>9} "
            f"{_fmt(r.cal_ece):>8} {_fmt(r.cal_brier):>9} {_fmt(r.cal_auc):>7}  {r.fit}"
        )
    return "\n".join(lines)


# ---- dòng lệnh ---------------------------------------------------------------------------------------------------------


def _cmd_build(args: argparse.Namespace) -> int:
    recorded = load_jsonl(args.with_path, RecordedCase)
    without = load_jsonl(args.without_path, WithoutRow)
    if args.out.resolve() in {args.with_path.resolve(), args.without_path.resolve()}:
        raise DataError("out: trùng file đầu vào")
    res = build_probs(recorded, without)
    write_jsonl(args.out, res.rows)
    n_no = sum(1 for r in res.rows if r.variant == "no_evidence")
    print(f"ca đi lớp LLM: {res.n_cases}")
    print(f"with_evidence: {res.n_cases}; no_evidence: {n_no}; max: {n_no}")
    print(f"no_evidence chép từ with_evidence do kb_gap (không gọi lại): {res.n_copied}")
    print(f"lỗi khi gọi no_evidence (bỏ no_evidence + max của ca đó): {sum(res.failed.values())} {res.failed or ''}".rstrip())
    print(f"thiếu dòng no_evidence (bỏ no_evidence + max của ca đó): {res.n_missing}")
    print(f"đã ghi {len(res.rows)} dòng → {args.out}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    recorded = load_jsonl(args.with_path, RecordedCase)
    rows = load_jsonl(args.probs, ProbRow)
    reports = compare_variants(recorded, rows, now=datetime.now(UTC))
    print(format_table(reports))
    print("chẩn đoán: fit Platt chỉ trên calibration, đo trên test; KHÔNG dùng để chọn biến thể (chọn ở fit_fold, theo chi phí).")
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        with args.json.open("x", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2) + "\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="prob_variants.py", description=__doc__.split("\n")[0] if __doc__ else None)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="ghép with_evidence + no_evidence + max → probs.jsonl")
    b.add_argument("with_path", type=Path, metavar="WITH.jsonl")
    b.add_argument("without_path", type=Path, metavar="WITHOUT.jsonl")
    b.add_argument("out", type=Path, metavar="OUT/probs.jsonl")
    b.set_defaults(fn=_cmd_build)
    c = sub.add_parser("compare", help="chẩn đoán ECE/Brier/AUC từng biến thể (không chọn)")
    c.add_argument("with_path", type=Path, metavar="WITH.jsonl")
    c.add_argument("probs", type=Path, metavar="probs.jsonl")
    c.add_argument("--json", type=Path, default=None)
    c.set_defaults(fn=_cmd_compare)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except (DataError, FileExistsError, FileNotFoundError) as e:
        print(f"LỖI: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
