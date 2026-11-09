"""Route offline của các phương án có lớp LLM (P8 v1.4 §5.3, §5.4; việc N18).

Bản đóng băng chạy CHƯA hiệu chỉnh (D-38), nên route của stack không phản ánh quy trình "fit calibrator + chọn ngưỡng theo chi phí".
Với mỗi phương án có LLM (Hybrid, Chỉ-LLM, Hybrid-guarded) và mỗi phần `i` của kiểm tra chéo 5 phần, module này fit trên 4 phần còn
lại (`calibrate.fit_fold`), rồi tính route cho phần đo `i`, và ghi `predictions.jsonl` (hợp đồng v1.1) + `manifest.json` cho `report.py`.
Số RQ1 của các phương án có LLM vì vậy là ƯỚC LƯỢNG của quy trình đó, tính bằng kiểm tra chéo trên xác suất thô đã ghi — nói rõ trong
báo cáo. Chỉ-luật không qua đây (route của stack).

  EVAL_MODE=true PYTHONPATH=backend uv run python -m app.eval.offline \\
      --s1 S1/predictions.jsonl S1/manifest.json S1/probs.jsonl --s2 S2/predictions.jsonl S2/manifest.json S2/probs.jsonl \\
      [--s3 S3/predictions.jsonl S3/manifest.json S3/probs.jsonl] --folds folds.csv --policy config/policy.json --out <thư mục mới>

Ca đi lớp LLM (P8 §5.4), p lấy theo `(scenario_id, variant)` trong `probs.jsonl` của lượt tương ứng:
- Hybrid (S1)           : ca `decided_by = llm`; ca `rule` giữ route luật.
- Chỉ-LLM (S2)          : MỌI ca có route (kể cả ca khớp luật ở chiến lược khác).
- Hybrid-guarded (S1+S2): ca `llm` của S1 và ca `rule` có route AUTO (luật CHO PHÉP), p từ S2; luật chặn/cần duyệt giữ route luật.
Ca đã nhãn không tới điểm log 4 (`route = None`), theo P8 §5.4 [Chốt 22/10] và trường `m5_aborted` của predictions v1.1: M5 bị ngắt
(`m5_aborted = true`) → ESCALATE_L2; không bị ngắt (`false`: E1, lỗi ở bước khác, kẹt B11…) → ngoài mẫu số; `null` → DỪNG. Cùng quy tắc ở
`report.py` cho mọi phương án (kể cả Chỉ-luật). Ca chưa nhãn → ngoài mẫu (giữ nguyên dòng). Hybrid-guarded mà S2 không tới điểm log 4
→ xét như trên theo dòng S2 (không có p của lớp LLM).
`--s3` (tuỳ chọn): Hybrid tắt chẩn đoán — chạy lại `compute_arm("hybrid")` với S3 làm nguồn (calibrator fit trên phần huấn luyện của CHÍNH
S3) → thư mục `hybrid_no_diag`.

Đầu vào giả định (tạm tới khi có `split.py`/SPLIT.md, D11): `--folds` CSV `family,fold` (fold 1..CV_K); `fold` khác null trong predictions
phải khớp CSV. `kb_gap` null ở ca đi lớp LLM → DỪNG (harness phải điền `kb_gap`; không đoán). `policy_sha256` của mọi manifest phải bằng
sha256 của file `--policy` (lệch/thiếu → dừng). `now` của `fit_platt` = `started_at` của manifest S1 (thiếu → dừng) để chạy lại ra cùng version.
Mã thoát: 0 xong; 2 dừng (dòng cuối `DỪNG: <lý do>`).
"""

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.eval.calibrate import (
    UNCALIBRATED_VARIANT,
    VARIANT_ORDER,
    FoldCase,
    FoldFit,
    Variant,
    fit_fold,
    llm_route,
)
from app.eval.predictions import CV_K, PredictionRecord, load_predictions, m5_outcome
from app.eval.report import Manifest, load_manifest
from app.risk.calibrator import save_calibrator
from app.risk.decision_math import DEFAULT_COST, CostMatrix, Route
from app.settings import parse_policy

ARMS: Final = ("hybrid", "llm_only", "hybrid_guarded")
OFFLINE_VERSION: Final = "n18-1"
NO_DIAG_ARM: Final = "hybrid_no_diag"  # S3: Hybrid tắt chẩn đoán chủ động (RQ3, ablation bỏ tool)
LIMITS: Final = (
    "Platt thường, không làm mượt nhãn (F3 không làm)",
    "select_thresholds không biết kb_gap; ngưỡng dưới giữ nguyên khi ép ngưỡng trên = 1,01",
    "S3 chỉ có route offline khi truyền --s3",
    "fold lấy từ CSV tạm, không phải SPLIT.md",
)

type Kind = Literal["llm", "fixed", "no_log4", "out"]


class StopError(Exception):
    """Dừng (mã thoát 2) — dữ liệu hoặc điều kiện sai. Thông điệp nêu tên trường/số lượng, KHÔNG in giá trị dữ liệu."""


class ProbLine(BaseModel):
    """Một dòng `probs.jsonl` (P8 §5.6): đúng 3 trường."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    scenario_id: str = Field(min_length=1)
    variant: Variant
    raw_prob: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


@dataclass(frozen=True)
class Run:
    """Một lượt chạy trên stack đã nạp (S1 hoặc S2)."""

    records: tuple[PredictionRecord, ...]
    manifest: Manifest
    raw_manifest: Mapping[str, Any]
    probs: Mapping[str, Mapping[Variant, float]]  # scenario_id → biến thể → p
    probs_sha256: str


# ---- nạp đầu vào -----------------------------------------------------------------------------------------------------


def load_probs(path: Path) -> tuple[dict[str, dict[Variant, float]], str]:
    try:
        raw = path.read_bytes()
        lines = raw.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        raise StopError("probs: không đọc được file (UTF-8)") from None
    if not lines:
        raise StopError("probs: file rỗng")
    out: dict[str, dict[Variant, float]] = {}
    for no, line in enumerate(lines, start=1):
        try:
            row = ProbLine.model_validate_json(line)
        except ValidationError as e:
            where = ", ".join(sorted({".".join(str(p) for p in err["loc"]) or "<dòng>" for err in e.errors()}))
            raise StopError(f"probs dòng {no}: không hợp lệ ({where})") from None
        by_variant = out.setdefault(row.scenario_id, {})
        if row.variant in by_variant:
            raise StopError(f"probs dòng {no}: trùng (scenario_id, variant)")
        by_variant[row.variant] = row.raw_prob
    return out, hashlib.sha256(raw).hexdigest()


def load_folds(path: Path) -> tuple[dict[str, int], str]:
    try:
        raw = path.read_bytes()
        reader = csv.DictReader(raw.decode("utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        raise StopError("folds: không đọc được file (UTF-8)") from None
    if reader.fieldnames is None or not {"family", "fold"} <= set(reader.fieldnames):
        raise StopError("folds: CSV cần hai cột family, fold")
    out: dict[str, int] = {}
    for no, row in enumerate(reader, start=1):
        family, text = (row["family"] or "").strip(), (row["fold"] or "").strip()
        if not family or not text.isdigit() or not 1 <= int(text) <= CV_K:
            raise StopError(f"folds dòng {no}: family rỗng hoặc fold ngoài 1..{CV_K}")
        if out.setdefault(family, int(text)) != int(text):
            raise StopError(f"folds dòng {no}: một họ ở hai phần khác nhau")
    if not out:
        raise StopError("folds: file rỗng")
    return out, hashlib.sha256(raw).hexdigest()


def load_run(predictions: Path, manifest: Path, probs: Path, *, strategy: str, diagnosis: bool = True) -> Run:
    try:
        mf = load_manifest(manifest)
        raw_mf = json.loads(manifest.read_text(encoding="utf-8"))
        records = load_predictions(predictions)
    except (ValueError, OSError) as e:
        raise StopError(f"{predictions.name}: {e}") from None
    first = records[0]
    if mf.run_id != first.run_id or mf.strategy != first.strategy:
        raise StopError(f"{predictions.name}: manifest và predictions lệch nhau (run_id hoặc strategy)")
    if first.strategy != strategy:
        raise StopError(f"{predictions.name}: strategy phải là {strategy}")
    if mf.diagnosis != diagnosis:
        raise StopError(f"{predictions.name}: lượt phải {'bật' if diagnosis else 'tắt'} chẩn đoán chủ động")
    by_sid, sha = load_probs(probs)
    known = {r.scenario_id for r in records}
    unknown = [s for s in by_sid if s not in known]
    if unknown:
        raise StopError(f"{probs.name}: {len(unknown)} scenario_id không có trong predictions cùng lượt")
    return Run(tuple(records), mf, raw_mf, by_sid, sha)


def check_runs(s1: Run, s2: Run) -> None:
    if s1.manifest.dataset_sha256 != s2.manifest.dataset_sha256:
        raise StopError("S1 và S2 khác dataset_sha256")
    gold1 = {r.scenario_id: (r.family, r.expected_route) for r in s1.records}
    gold2 = {r.scenario_id: (r.family, r.expected_route) for r in s2.records}
    if gold1 != gold2:
        raise StopError("S1 và S2 khác tập scenario_id, họ hoặc gold")


def read_policy_t_high(policy: Path, runs: Sequence[Run]) -> tuple[float, str]:
    """Ngưỡng trên của policy bản đóng băng (D-38) — đọc từ file, không ghi cứng; sha256 phải khớp `policy_sha256` của manifest."""
    try:
        data = policy.read_bytes()
    except OSError:
        raise StopError("policy: không đọc được file") from None
    sha = hashlib.sha256(data).hexdigest()
    for r in runs:
        if r.manifest.policy_sha256 is None:
            raise StopError("manifest: thiếu policy_sha256 — không kiểm được bản luật đóng băng")
        if r.manifest.policy_sha256 != sha:
            raise StopError("policy_sha256 của manifest khác sha256 của file --policy (sai bản luật)")
    try:
        return parse_policy(data).constants.THRESHOLD_HIGH, sha
    except ValueError:
        raise StopError("policy: file không hợp lệ") from None


def started_at(s1: Run) -> datetime:
    text = s1.raw_manifest.get("started_at")
    try:
        t = datetime.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        t = None
    if t is None or t.utcoffset() is None:
        raise StopError("manifest S1: thiếu started_at (ISO 8601 có múi giờ) — cần cho version calibrator tái lập")
    return t


# ---- phân loại ca theo phương án ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmRow:
    base: PredictionRecord  # dòng nguồn để ghi ra
    fold: int
    kind: Kind  # llm | fixed (route luật) | no_log4 (→ ESCALATE_L2) | out (chưa nhãn, hoặc E1 — ngoài mẫu)
    fixed_route: Route | None
    src: PredictionRecord | None  # dòng mang p_method của ca LLM (cùng lượt với probs)
    probs: Mapping[Variant, float]
    kb_gap: bool | None

    def case(self, split: Literal["calibration", "test"]) -> FoldCase:
        gold = self.base.expected_route
        assert gold is not None  # kind ≠ out ⇒ đã nhãn
        if self.kind == "llm":
            assert self.kb_gap is not None  # classify() dừng trước nếu null
            return FoldCase(self.base.scenario_id, self.base.family, split, gold, True, None, self.probs, self.kb_gap)
        route: Route | None = "ESCALATE_L2" if self.kind == "no_log4" else self.fixed_route
        assert route is not None  # kind fixed luôn mang route luật
        return FoldCase(self.base.scenario_id, self.base.family, split, gold, False, route, {}, False)


def _no_log4(r: PredictionRecord) -> Kind:
    """Lá đã nhãn mà `route = None` (P8 §5.4 [Chốt 22/10]) — quy tắc DÙNG CHUNG với `report.py` (`predictions.m5_outcome`):
    M5 bị ngắt (`m5_aborted`: hết hạn lượt / lỗi không lường tại `S_ASSESSING`) → ESCALATE_L2 với phương án có LLM; không bị ngắt (E1,
    lỗi ở bước khác, kẹt B11…) → ngoài mẫu số; `m5_aborted` null → dừng (collector phải điền)."""
    try:
        return "no_log4" if m5_outcome(r) == "aborted" else "out"
    except ValueError as e:
        raise StopError(str(e)) from None


def classify(arm: str, s1: Run, s2: Run, folds: Mapping[str, int]) -> list[ArmRow]:
    """Mỗi lá của phương án → ArmRow (P8 §5.4). Dòng theo thứ tự của file nguồn (S2 cho Chỉ-LLM, S1 cho hai phương án còn lại)."""
    by2 = {r.scenario_id: r for r in s2.records}
    base_run = s2 if arm == "llm_only" else s1
    probs_run = s1 if arm == "hybrid" else s2
    unmapped = {r.family for r in base_run.records} - folds.keys()
    if unmapped:
        raise StopError(f"folds: {len(unmapped)} họ không có phần trong CSV — mọi họ phải có phần")
    rows: list[ArmRow] = []
    null_gap = 0
    for base in base_run.records:
        fold = folds[base.family]
        if base.fold is not None and base.fold != fold:
            raise StopError("fold trong predictions khác CSV --folds")
        r2 = by2[base.scenario_id]
        if base.expected_route is None:
            rows.append(ArmRow(base, fold, "out", None, None, {}, None))
            continue
        if base.route is None:
            rows.append(ArmRow(base, fold, _no_log4(base), None, None, {}, None))
            continue
        if base.decided_by is None:
            raise StopError("decided_by thiếu ở lá đã tới điểm log 4")
        to_llm = base.decided_by == "llm"
        if arm == "llm_only" and not to_llm:
            raise StopError("S2 (llm_only) có lá do luật quyết")
        if arm == "hybrid_guarded" and base.decided_by == "rule" and base.route == "AUTO":
            to_llm = True  # luật CHO PHÉP → lớp LLM xét thêm (P8 §5.4)
        if not to_llm:
            rows.append(ArmRow(base, fold, "fixed", base.route, None, {}, None))
            continue
        src = base if arm != "hybrid_guarded" else r2
        if arm == "hybrid_guarded" and r2.route is None:
            rows.append(ArmRow(base, fold, _no_log4(r2), None, None, {}, None))  # S2 không tới điểm log 4: không có p của lớp LLM
            continue
        if arm == "hybrid_guarded" and r2.decided_by != "llm":
            raise StopError("S2 (llm_only) có lá không do lớp LLM quyết")
        probs = dict(probs_run.probs.get(base.scenario_id, {}))
        if "with_evidence" not in probs:
            raise StopError("probs: thiếu with_evidence của một ca đi lớp LLM")
        if src.raw_prob is not None and src.raw_prob != probs["with_evidence"]:
            raise StopError("probs: with_evidence khác raw_prob trong predictions cùng lượt (nhầm file S1/S2?)")
        null_gap += src.kb_gap is None
        rows.append(ArmRow(base, fold, "llm", None, src, probs, src.kb_gap))
    if null_gap:
        raise StopError(f"kb_gap null ở {null_gap} ca đi lớp LLM — harness phải điền kb_gap (không đoán)")
    return rows


# ---- tính từng phần ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmResult:
    arm: str
    records: tuple[PredictionRecord, ...]
    fits: Mapping[int, FoldFit | None]  # None: phần không có ca đo
    reports: tuple[dict[str, Any], ...]
    counts: Mapping[str, int]
    selection: Mapping[str, int]  # biến thể (hoặc "uncalibrated") → số phần


def _update(row: ArmRow, fit: FoldFit | None, policy_t_high: float, counts: Counter[str]) -> dict[str, Any]:
    """Các trường đổi của một dòng ở phần đo."""
    up: dict[str, Any] = {"fold": row.fold}
    if row.kind == "no_log4":
        counts["no_log4_to_l2"] += 1
        up |= {"route": "ESCALATE_L2", "decided_by": None, "raw_prob": None, "calibrated_prob": None, "p_method": None,
               "kb_gap": None}  # fmt: skip
    elif row.kind == "llm":
        assert fit is not None and row.src is not None
        variant = fit.variant or UNCALIBRATED_VARIANT
        p = row.probs.get(variant)
        up |= {"decided_by": "llm", "p_method": row.src.p_method, "kb_gap": row.kb_gap}
        if p is None:  # biến thể được chọn bị bỏ ở ca này (G10 gọi lỗi) → chuyển L2
            counts["missing_p_to_l2"] += 1
            up |= {"route": "ESCALATE_L2", "raw_prob": None, "calibrated_prob": None}
        else:
            cal = fit.calibrator
            up |= {
                "route": llm_route(p, cal, fit.thresholds, bool(row.kb_gap), policy_t_high),
                "raw_prob": p, "calibrated_prob": cal.transform(p) if cal is not None else None,
            }  # fmt: skip
    return up


def compute_arm(
    arm: str, rows: Sequence[ArmRow], *, now: datetime, policy_t_high: float, derived_run_id: str | None = None,
    cost: CostMatrix = DEFAULT_COST, name: str | None = None,
) -> ArmResult:  # fmt: skip
    """`arm` = phương án tính (hybrid | llm_only | hybrid_guarded); `name` = tên thư mục/nhãn đầu ra (mặc định `arm`; S3 → hybrid_no_diag)."""
    label = name or arm
    in_sample = [r for r in rows if r.kind != "out"]
    updates: dict[str, dict[str, Any]] = {}
    fits: dict[int, FoldFit | None] = {}
    reports: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    selection: Counter[str] = Counter()
    for i in range(1, CV_K + 1):
        test = [r for r in in_sample if r.fold == i]
        train = [r.case("calibration") for r in in_sample if r.fold != i]
        if not test:
            fits[i] = None
            reports.append({"arm": label, "fold": i, "note": "không có ca đo ở phần này", "n_train": len(train)})
            continue
        fit = fit_fold(train, now=now, policy_t_high=policy_t_high, cost=cost)
        fits[i] = fit
        local: Counter[str] = Counter()
        for r in test:
            updates[r.base.scenario_id] = _update(r, fit, policy_t_high, local)
        counts.update(local)
        selection[fit.variant or "uncalibrated"] += 1
        reports.append({"arm": label, "fold": i, "n_test": len(test), "n_test_llm": sum(r.kind == "llm" for r in test),
                        "no_log4_to_l2": local["no_log4_to_l2"], "missing_p_to_l2": local["missing_p_to_l2"],
                        **fit.to_dict()})  # fmt: skip
    out: list[PredictionRecord] = []
    for r in rows:
        up = updates.get(r.base.scenario_id, {"fold": r.fold})
        if derived_run_id is not None:
            up = {**up, "run_id": derived_run_id, "strategy": "hybrid_guarded"}
        out.append(PredictionRecord.model_validate({**r.base.model_dump(), **up}))
    counts["rows"] = len(rows)
    counts["llm"] = sum(r.kind == "llm" for r in rows)
    counts["fixed"] = sum(r.kind == "fixed" for r in rows)
    counts["out"] = sum(r.kind == "out" for r in rows)
    counts["unlabeled"] = sum(r.base.expected_route is None for r in rows)
    counts["folds_uncalibrated"] = selection["uncalibrated"]
    counts["folds_upper_disabled"] = sum(1 for f in fits.values() if f is not None and f.upper_disabled is not None)
    return ArmResult(label, tuple(out), fits, tuple(reports), dict(counts), dict(selection))


# ---- ghi ra ----------------------------------------------------------------------------------------------------------


def _write_new(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_arm(out: Path, result: ArmResult, manifest: Mapping[str, Any]) -> None:
    d = out / result.arm
    (d / "folds").mkdir(parents=True)
    _write_new(d / "predictions.jsonl", "".join(r.model_dump_json() + "\n" for r in result.records))
    _write_new(d / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    for i, rep in enumerate(result.reports, start=1):
        _write_new(d / "folds" / f"{i}.json", json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    cals = [f.calibrator for f in result.fits.values() if f is not None and f.calibrator is not None]
    if cals:
        (d / "calibrators").mkdir()
        for cal in cals:
            save_calibrator(cal, d / "calibrators")


def derived_run_id(s1: Run, s2: Run) -> str:
    """`run_id` của Hybrid-guarded (ghép S1 + S2, không có lượt stack riêng)."""
    return hashlib.sha256(f"{s1.manifest.run_id}|{s2.manifest.run_id}|hybrid_guarded".encode()).hexdigest()[:12]


def arm_manifest(
    arm: str, s1: Run, s2: Run, result: ArmResult, extra: Mapping[str, Any], s3: Run | None = None
) -> dict[str, Any]:  # fmt: skip
    """Manifest của phương án: nguồn S2 (Chỉ-LLM), S3 (hybrid_no_diag) hoặc S1; Hybrid-guarded thêm `run_id` mới + `derived_from`."""
    src = s2 if arm == "llm_only" else (s3 if arm == NO_DIAG_ARM and s3 is not None else s1)
    mf: dict[str, Any] = dict(src.raw_manifest)
    mf["predictions_unavailable"] = [u for u in mf.get("predictions_unavailable", []) if u != "fold"]
    if arm == "hybrid_guarded":
        mf |= {"run_id": derived_run_id(s1, s2), "strategy": "hybrid_guarded",
               "derived_from": {"hybrid_run_id": s1.manifest.run_id, "llm_only_run_id": s2.manifest.run_id,
                                "hybrid_git_commit": s1.manifest.git_commit, "llm_only_git_commit": s2.manifest.git_commit}}  # fmt: skip
    mf["offline"] = {**extra, "selection": dict(result.selection), "counts": dict(result.counts)}
    return mf


def run_all(
    s1: Run, s2: Run, folds: Mapping[str, int], *, now: datetime, policy_t_high: float, s3: Run | None = None
) -> dict[str, ArmResult]:  # fmt: skip
    out: dict[str, ArmResult] = {}
    for arm in ARMS:
        rows = classify(arm, s1, s2, folds)
        run_id = derived_run_id(s1, s2) if arm == "hybrid_guarded" else None
        out[arm] = compute_arm(arm, rows, now=now, policy_t_high=policy_t_high, derived_run_id=run_id)
    if s3 is not None:  # S3 là một lượt Hybrid khác: calibrator fit trên phần huấn luyện của chính S3
        out[NO_DIAG_ARM] = compute_arm(
            "hybrid", classify("hybrid", s3, s2, folds), now=now, policy_t_high=policy_t_high, name=NO_DIAG_ARM
        )  # fmt: skip
    return out


# ---- dòng lệnh -------------------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.eval.offline", description="Route offline của Hybrid, Chỉ-LLM, Hybrid-guarded (P8 §5.3)")
    p.add_argument("--s1", nargs=3, type=Path, required=True, metavar=("PREDICTIONS", "MANIFEST", "PROBS"))
    p.add_argument("--s2", nargs=3, type=Path, required=True, metavar=("PREDICTIONS", "MANIFEST", "PROBS"))
    p.add_argument("--s3", nargs=3, type=Path, default=None, metavar=("PREDICTIONS", "MANIFEST", "PROBS"),
                   help="tuỳ chọn: Hybrid tắt chẩn đoán → thư mục hybrid_no_diag")  # fmt: skip
    p.add_argument("--folds", type=Path, required=True, metavar="CSV")
    p.add_argument("--policy", type=Path, required=True, metavar="policy.json")
    p.add_argument("--out", type=Path, required=True, metavar="DIR")
    args = p.parse_args(argv)
    try:
        s1 = load_run(*args.s1, strategy="hybrid")
        s2 = load_run(*args.s2, strategy="llm_only")
        s3 = load_run(*args.s3, strategy="hybrid", diagnosis=False) if args.s3 is not None else None
        check_runs(s1, s2)
        if s3 is not None:
            check_runs(s1, s3)
        folds, folds_sha = load_folds(args.folds)
        t_high, policy_sha = read_policy_t_high(args.policy, tuple(r for r in (s1, s2, s3) if r is not None))
        now = started_at(s1)
        if args.out.exists():
            raise StopError("--out đã tồn tại — dùng thư mục mới")
        results = run_all(s1, s2, folds, now=now, policy_t_high=t_high, s3=s3)
        args.out.mkdir(parents=True)
        extra = {"version": OFFLINE_VERSION, "now": now.isoformat(), "folds_sha256": folds_sha, "policy_sha256": policy_sha,
                 "probs_sha256": {"s1": s1.probs_sha256, "s2": s2.probs_sha256, **({"s3": s3.probs_sha256} if s3 else {})},
                 "cost_matrix": "DEFAULT_COST (10:1)",
                 "variant_order": list(VARIANT_ORDER), "limits": list(LIMITS)}  # fmt: skip
        for arm, result in results.items():
            write_arm(args.out, result, arm_manifest(arm, s1, s2, result, extra, s3))
            c = result.counts
            print(f"{arm}: lá {c['rows']}, đi lớp LLM {c['llm']}, route luật {c['fixed']}, ngoài mẫu {c['out']} "
                  f"(chưa nhãn {c['unlabeled']}), không tới điểm log 4 → L2 {c.get('no_log4_to_l2', 0)}, "
                  f"thiếu p biến thể được chọn → L2 {c.get('missing_p_to_l2', 0)}")  # fmt: skip
            print(f"  biến thể được chọn (số phần): {dict(result.selection)}; phần chưa hiệu chỉnh: {c['folds_uncalibrated']}; "
                  f"phần ép ngưỡng trên = 1,01: {c['folds_upper_disabled']}")  # fmt: skip
    except StopError as e:
        print(f"DỪNG: {e}", file=sys.stderr)
        return 2
    except FileExistsError:
        print("DỪNG: file đầu ra đã tồn tại", file=sys.stderr)
        return 2
    print(f"đã ghi {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
