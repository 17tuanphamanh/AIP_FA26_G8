"""Bảng và số liệu báo cáo M8 (P8 v1.4 §6, §7) — RQ1, RQ3, độ nhạy mix, điểm hoà vốn, bootstrap theo họ. Chỉ GỌI `metrics.py`,
`stats.py`, `predictions.py`, `decision_math` rồi định dạng; không tính route offline (việc của `offline.py`, chưa có).

Đầu vào: mỗi phương án một cặp `predictions.jsonl` (hợp đồng v1.1) + `manifest.json` của lượt chạy sinh ra nó (không có manifest thì
không đưa số vào báo cáo — P8 §5.1). Phương án lấy từ trường `strategy` của file: `rule_only`, `llm_only`, `hybrid`,
`hybrid_guarded`. Lượt S3 (Hybrid tắt chẩn đoán) nhận ra bằng `enable_proactive_diagnosis = false` ở manifest. Thủ công và Full-auto
là giải tích: dựng từ phần giao của các phương án (`manual_baseline`, `full_auto_baseline`), không đọc từ file.

Quy ước:
- Chỉ nhận `split = "test"` (số của phần calibration không được lọt vào báo cáo). Mọi file cùng `dataset_sha256`, cùng `split`, cùng tập
  `scenario_id`, cùng gold; lệch → `ValueError`. Commit hoặc `policy_sha256` khác nhau chỉ là CẢNH BÁO (P8 §5.5 yêu cầu cùng tag).
- **Phần giao** (P8 §5.4): lá đã nhãn có `route` ở MỌI phương án RQ1. Chi phí, an toàn, độ nhạy so trên phần giao; Thủ công và
  Full-auto tính trên đúng phần giao đó (chốt G1-Q1, #32 22/10). Hoà vốn (T7) cũng trên phần giao đó (G5) → đối chiếu được T1.
- Số chính RQ1 = chi phí kỳ vọng KHÔNG trọng số (§6.1, ma trận mặc định). Bản có trọng số và hai độ nhạy là số phụ.
- Mọi bảng có sáu cột đầu `run_id, dataset_sha256, git_commit, n, n_unlabeled, n_excluded`. `n` = số lá trong mẫu của bảng,
  `n_unlabeled` = lá chưa nhãn của file, `n_excluded` = lá đã nhãn không vào mẫu (route None hoặc ngoài phần giao).
- Bootstrap theo họ (`family`, §4.3), 2.000 lần, seed cố định — không đổi dù có ánh xạ tình huống.
- Đơn vị "tình huống" của FNR (§6.1): `situation_id` từ `--situations`; không có file → lùi về họ và CẢNH BÁO ở T3a, T4.

Không biểu đồ (không có matplotlib), không `folds/<i>.json`, không "10 ca sai tiêu biểu" (cần DB): ngoài phạm vi file này.

  EVAL_MODE=true PYTHONPATH=backend uv run python -m app.eval.report \\
      --arm S1/predictions.jsonl S1/manifest.json --arm S2/predictions.jsonl S2/manifest.json ... --out <thư mục mới>
"""

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn

from app.eval.metrics import (
    BREAKEVEN_RATIOS,
    OPERATING_MIX,
    SENSITIVITY_MIXES,
    Group,
    Hidden,
    SituationFnr,
    UnitOf,
    breakeven,
    calibration_scores,
    decided_by_distribution,
    efficiency,
    full_auto_baseline,
    manual_baseline,
    mean_route_cost,
    operating_metrics,
    safety,
    situation_fnr,
)
from app.eval.predictions import SCHEMA_VERSION, PredictionRecord, load_predictions
from app.eval.stats import (
    BOOTSTRAP_N,
    SEED,
    BootstrapCI,
    PairedDiffCI,
    family_bootstrap_ci,
    paired_family_bootstrap_diff,
)
from app.risk.decision_math import (
    cost_matrix_for_ratio,
    t_low_star,
)

type Cell = str | int | float | bool | None
type Records = Sequence[PredictionRecord]

RQ1_STRATEGIES: Final = ("rule_only", "llm_only", "hybrid", "hybrid_guarded")
LLM_ARMS: Final = ("llm_only", "hybrid", "hybrid_guarded")  # có lớp LLM (P8 §5.4)
NO_TOOL: Final = "hybrid_no_tool"  # lượt S3
ANALYTIC: Final = ("manual", "full_auto")
ORDER: Final = (*ANALYTIC, *RQ1_STRATEGIES)
LABEL: Final = {
    "manual": "Thủ công", "full_auto": "Full-auto", "rule_only": "Chỉ-luật", "llm_only": "Chỉ-LLM", "hybrid": "Hybrid",
    "hybrid_guarded": "Hybrid-guarded", NO_TOOL: "Hybrid (tắt chẩn đoán, S3)",
}  # fmt: skip
SAFETY_UPPER_LIMIT: Final = 0.10  # P8 §6.5 vế 2: cận trên một phía 95% của FNR theo tình huống < 10%
MIXES: Final[Mapping[str, Mapping[Group, float] | None]] = {"không trọng số": None, "70/20/10": OPERATING_MIX, **SENSITIVITY_MIXES}
META_COLS: Final = ("run_id", "dataset_sha256", "git_commit", "n", "n_unlabeled", "n_excluded")
UNIT_FAMILY: Final = "họ (family)"
UNIT_SITUATION: Final = "tình huống (situation_id)"
NO_MAPPING_WARNING: Final = "CẢNH BÁO: đơn vị = họ, chưa có ánh xạ tình huống (--situations). Họ chứa nhiều tình huống làm FNR sai lệch."
PASS: Final = "đạt"
FAIL: Final = "không đạt"
NO_DIFF: Final = "chưa đủ bằng chứng khác biệt"
UNKNOWN: Final = "không kết luận được"

# ---- đầu vào -----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Manifest:
    run_id: str
    git_commit: str
    git_dirty: bool | None
    dataset_sha256: str
    strategy: str
    split: str
    schema_version: str
    diagnosis: bool
    policy_sha256: str | None
    clf_mode: str | None
    unavailable: tuple[str, ...]


@dataclass(frozen=True)
class Arm:
    """Một lượt chạy: tên hiển thị (`strategy`, hoặc `hybrid_no_tool` cho S3), bản ghi lá, manifest."""

    name: str
    records: tuple[PredictionRecord, ...]
    manifest: Manifest
    source: str


@dataclass(frozen=True)
class Situations:
    """Ánh xạ `scenario_id → situation_id` (§4.1: một họ chứa nhiều tình huống). `sha256` = mã băm file nguồn."""

    mapping: Mapping[str, str]
    source: str
    sha256: str


def _opt_str(data: Mapping[str, object], key: str) -> str | None:
    v = data.get(key)
    if v is not None and not isinstance(v, str):
        raise ValueError(f"manifest: khoá {key} sai kiểu")
    return v


def load_manifest(path: Path) -> Manifest:
    if not path.is_file():
        raise ValueError("manifest: không có file — không có manifest thì không đưa số vào báo cáo (P8 §5.1)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("manifest: không đọc được JSON") from None
    if not isinstance(data, dict):
        raise ValueError("manifest: phải là một đối tượng JSON")  # noqa: TRY004
    required: dict[str, str] = {}
    for key in ("run_id", "git_commit", "dataset_sha256", "strategy", "split", "schema_version"):
        v = data.get(key)
        if not isinstance(v, str) or not v:
            raise ValueError(f"manifest: thiếu hoặc sai kiểu khoá {key}")
        required[key] = v
    diagnosis = data.get("enable_proactive_diagnosis")
    if not isinstance(diagnosis, bool):
        raise ValueError("manifest: thiếu hoặc sai kiểu khoá enable_proactive_diagnosis")  # noqa: TRY004
    dirty = data.get("git_dirty")
    if dirty is not None and not isinstance(dirty, bool):
        raise ValueError("manifest: khoá git_dirty sai kiểu")
    unavailable = data.get("predictions_unavailable", [])
    if not isinstance(unavailable, list) or not all(isinstance(u, str) for u in unavailable):
        raise ValueError("manifest: khoá predictions_unavailable phải là danh sách chuỗi")
    return Manifest(
        git_dirty=dirty, diagnosis=diagnosis, policy_sha256=_opt_str(data, "policy_sha256"),
        clf_mode=_opt_str(data, "clf_mode"), unavailable=tuple(unavailable), **required,
    )  # fmt: skip


def load_arm(predictions: Path, manifest: Path) -> Arm:
    """Nạp một lượt chạy. Từ chối: thiếu manifest, `schema_version` ≠ 1.1, `run_id`/`strategy` lệch nhau, `split` ≠ test,
    phương án ngoài `RQ1_STRATEGIES`, lượt tắt chẩn đoán mà không phải Hybrid."""
    mf = load_manifest(manifest)
    records = load_predictions(predictions)
    first = records[0]
    if mf.schema_version != SCHEMA_VERSION:
        raise ValueError(f"manifest: schema_version phải là {SCHEMA_VERSION}")
    if mf.run_id != first.run_id or mf.strategy != first.strategy:
        raise ValueError("manifest và predictions lệch nhau (run_id hoặc strategy) — không phải cùng một lượt chạy")
    if first.split != "test" or mf.split != "test":
        raise ValueError("split ≠ test — số của phần calibration không được vào báo cáo (P8 §5.1)")
    if first.strategy not in RQ1_STRATEGIES:
        raise ValueError(f"strategy {first.strategy}: chỉ nhận {', '.join(RQ1_STRATEGIES)} (Thủ công, Full-auto là giải tích)")
    name: str
    if mf.diagnosis:
        name = first.strategy
    elif first.strategy == "hybrid":
        name = NO_TOOL
    else:
        raise ValueError("enable_proactive_diagnosis = false chỉ hợp lệ với lượt S3 (strategy hybrid)")
    return Arm(name, tuple(records), mf, predictions.name)


def load_situations(path: Path) -> Situations:
    """CSV (cột `scenario_id`, `situation_id`) hoặc JSON (`{scenario_id: situation_id}` hoặc danh sách `{scenario_id,
    situation_id}`). Trùng `scenario_id` khác tình huống, ô rỗng → `ValueError` (lỗi chỉ nêu dòng/vị trí, không in giá trị)."""
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise ValueError("situations: không đọc được file (UTF-8)") from None
    pairs: list[tuple[str, str]] = []
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(text.splitlines())
        if reader.fieldnames is None or not {"scenario_id", "situation_id"} <= set(reader.fieldnames):
            raise ValueError("situations: CSV cần hai cột scenario_id, situation_id")
        pairs = [(row["scenario_id"] or "", row["situation_id"] or "") for row in reader]
    elif path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except ValueError:
            raise ValueError("situations: JSON không hợp lệ") from None
        if isinstance(data, dict):
            pairs = [(k, v) for k, v in data.items() if isinstance(v, str)]
            if len(pairs) != len(data):
                raise ValueError("situations: giá trị situation_id phải là chuỗi")
        elif isinstance(data, list) and all(isinstance(d, dict) for d in data):
            pairs = [(str(d.get("scenario_id") or ""), str(d.get("situation_id") or "")) for d in data]
        else:
            raise ValueError("situations: JSON phải là đối tượng hoặc danh sách đối tượng")
    else:
        raise ValueError("situations: chỉ nhận .csv hoặc .json")
    mapping: dict[str, str] = {}
    for no, (sid, unit) in enumerate(pairs, start=1):
        if not sid.strip() or not unit.strip():
            raise ValueError(f"situations mục {no}: scenario_id hoặc situation_id rỗng")
        if mapping.setdefault(sid, unit) != unit:
            raise ValueError(f"situations mục {no}: scenario_id trùng nhưng khác situation_id")
    if not mapping:
        raise ValueError("situations: file rỗng")
    return Situations(mapping, path.name, hashlib.sha256(raw).hexdigest())


def check_arms(arms: Sequence[Arm]) -> None:
    """Kiểm chéo các lượt chạy; lệch → `ValueError`. Cần ít nhất một lượt RQ1 (bật chẩn đoán); không trùng tên."""
    if not any(a.manifest.diagnosis for a in arms):
        raise ValueError("arms: cần ít nhất một lượt RQ1 (bật chẩn đoán)")
    names = [a.name for a in arms]
    if len(set(names)) != len(names):
        raise ValueError("arms: hai lượt cùng phương án")
    ref = arms[0]
    gold = {r.scenario_id: (r.family, r.expected_route, r.gold_intent) for r in ref.records}
    for a in arms:
        if a.manifest.dataset_sha256 != ref.manifest.dataset_sha256:
            raise ValueError("arms: dataset_sha256 khác nhau — không so hai lượt trên hai bộ dữ liệu")
        if {r.split for r in a.records} != {r.split for r in ref.records}:
            raise ValueError("arms: split khác nhau")
        if {r.scenario_id: (r.family, r.expected_route, r.gold_intent) for r in a.records} != gold:
            raise ValueError("arms: tập scenario_id, họ hoặc gold khác nhau giữa các lượt")


# ---- kết luận RQ1 (P8 §6.5) --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rq1Verdict:
    """Từng vế `đạt` / `không đạt` / `chưa đủ bằng chứng khác biệt` / `không kết luận được` (thiếu dữ liệu)."""

    cost_vs_rule: str
    cost_vs_llm: str
    safety: str
    overall: str


def _cost_status(diff: PairedDiffCI | None) -> str:
    """Vế 1: khoảng của hiệu (Hybrid − X) nằm HẲN dưới 0 (`hi < 0`) → đạt; chứa 0 → chưa đủ bằng chứng; hẳn trên 0 → không đạt."""
    if diff is None or diff.lo is None or diff.hi is None:
        return UNKNOWN
    if diff.hi < 0:
        return PASS
    return NO_DIFF if diff.lo <= 0 else FAIL


def rq1_verdict(vs_rule: PairedDiffCI | None, vs_llm: PairedDiffCI | None, fnr: SituationFnr | None) -> Rq1Verdict:
    """P8 §6.5: "Hybrid tốt hơn" khi CẢ HAI — (1) khoảng hiệu chi phí Hybrid − Chỉ-luật và Hybrid − Chỉ-LLM nằm hẳn dưới 0;
    (2) cận trên một phía 95% của FNR theo tình huống trên tình huống cần người đi qua lớp LLM của Hybrid < 10%. Không đạt vế nào
    thì báo đúng vế đó; thiếu dữ liệu ở vế nào thì vế đó `không kết luận được` (không đoán)."""
    rule, llm = _cost_status(vs_rule), _cost_status(vs_llm)
    if fnr is None or fnr.upper95 is None:
        safe = UNKNOWN
    else:
        safe = PASS if fnr.upper95 < SAFETY_UPPER_LIMIT else FAIL
    parts = (("vế 1 (chi phí so Chỉ-luật)", rule), ("vế 1 (chi phí so Chỉ-LLM)", llm), ("vế 2 (an toàn)", safe))
    failed = [name for name, s in parts if s in (FAIL, NO_DIFF)]
    unknown = [name for name, s in parts if s == UNKNOWN]
    if not failed and not unknown:
        overall = "Hybrid tốt hơn: cả hai vế đạt"
    else:
        overall = "; ".join(
            ([f"không đạt: {', '.join(failed)}"] if failed else []) + ([f"chưa kết luận được: {', '.join(unknown)}"] if unknown else [])
        )
    return Rq1Verdict(rule, llm, safe, overall)


# ---- bảng --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Table:
    key: str
    section: str
    title: str
    columns: tuple[str, ...]  # gồm META_COLS đứng đầu
    rows: tuple[tuple[Cell, ...], ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    run_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    tables: tuple[Table, ...]
    verdict: Rq1Verdict


@dataclass(frozen=True)
class _Meta:
    run_id: str
    dataset_sha256: str
    git_commit: str
    n: int
    n_unlabeled: int
    n_excluded: int

    def cells(self) -> tuple[Cell, ...]:
        return (self.run_id, self.dataset_sha256, self.git_commit, self.n, self.n_unlabeled, self.n_excluded)


class _Builder:
    def __init__(self, key: str, section: str, title: str, columns: Sequence[str], notes: Sequence[str] = ()) -> None:
        self.key, self.section, self.title = key, section, title
        self.columns = (*META_COLS, *columns)
        self.notes = list(notes)
        self.rows: list[tuple[Cell, ...]] = []

    def add(self, meta: _Meta, *cells: Cell) -> None:
        if len(cells) != len(self.columns) - len(META_COLS):
            raise ValueError(f"bảng {self.key}: số ô không khớp số cột")
        self.rows.append((*meta.cells(), *cells))

    def build(self) -> Table:
        return Table(self.key, self.section, self.title, self.columns, tuple(self.rows), tuple(self.notes))


class _Ctx:
    """Dữ liệu dùng chung của các bảng: phương án, phần giao, mẫu từng phương án (kể cả giải tích), đơn vị tình huống."""

    def __init__(self, arms: Sequence[Arm], situations: Situations | None, n_boot: int, seed: int) -> None:
        check_arms(arms)
        self.n_boot, self.seed = n_boot, seed
        self.arms = {a.name: a for a in arms}
        self.ref = arms[0]
        self.rq1 = {a.name: a for a in arms if a.manifest.diagnosis}
        self.s3 = self.arms.get(NO_TOOL)
        sids = {r.scenario_id for r in self.ref.records}
        if situations is not None:
            missing = sids - situations.mapping.keys()
            if missing:
                raise ValueError(f"situations: thiếu ánh xạ cho {len(missing)} scenario_id của dữ liệu")
            self.mapping: Mapping[str, str] | None = situations.mapping
        else:
            self.mapping = None
        self.situations = situations
        self.unit_label = UNIT_FAMILY if self.mapping is None else UNIT_SITUATION
        self.n_unlabeled = sum(r.expected_route is None for r in self.ref.records)
        self.n_labelled = len(self.ref.records) - self.n_unlabeled
        reached = [{r.scenario_id for r in a.records if r.expected_route is not None and r.route is not None}
                   for a in self.rq1.values()]  # fmt: skip
        self.common: frozenset[str] = frozenset.intersection(*(frozenset(s) for s in reached))
        self.sample: dict[str, list[PredictionRecord]] = {n: self.restrict(a.records) for n, a in self.rq1.items()}
        base = self.sample.get("hybrid") or next(iter(self.sample.values()))
        self.base_name = "hybrid" if "hybrid" in self.sample else next(iter(self.sample))
        self.sample["manual"] = manual_baseline(base)  # route ≠ None → HITL; trên đúng phần giao (G1-Q1)
        self.sample["full_auto"] = full_auto_baseline(base)
        self.names = [n for n in ORDER if n in self.sample]

    def restrict(self, records: Records) -> list[PredictionRecord]:
        return [r for r in records if r.scenario_id in self.common]

    def unit_of(self) -> UnitOf | None:
        m = self.mapping
        return None if m is None else (lambda r: m[r.scenario_id])

    def meta(self, names: Sequence[str], n: int, *, n_unlabeled: int | None = None, n_excluded: int | None = None) -> _Meta:
        runs: list[str] = []
        commits: list[str] = []
        for name in names:
            arm = self.arms.get(name)
            run = arm.manifest.run_id if arm is not None else f"{name}@{self.rq1[self.base_name].manifest.run_id}"
            commit = (arm or self.rq1[self.base_name]).manifest.git_commit
            runs += [] if run in runs else [run]
            commits += [] if commit in commits else [commit]
        unl = self.n_unlabeled if n_unlabeled is None else n_unlabeled
        exc = max(self.n_labelled - n, 0) if n_excluded is None else n_excluded
        return _Meta("+".join(runs), self.ref.manifest.dataset_sha256, "+".join(commits), n, unl, exc)

    def label(self, name: str) -> str:
        return LABEL[name]


def _cost_stat(rs: Records) -> float | None:
    return mean_route_cost(rs).value


def _t0(c: _Ctx) -> Table:
    t = _Builder("t0_provenance", "Nguồn số liệu", "T0 — Nguồn số liệu (manifest)",
                 ("arm", "strategy", "chan_doan_chu_dong", "policy_sha256", "clf_mode", "git_dirty", "n_leaves", "n_route_none",
                  "predictions_unavailable", "file"),
                 ("Mỗi dòng một lượt chạy thật. Thủ công và Full-auto là giải tích, dựng từ phần giao của các phương án (không có dòng riêng).",
                  "Ở bảng này `n` = số lá của file, `n_excluded` = lá không tới điểm log 4 (route None).")
                 + ((f"Ánh xạ tình huống: {c.situations.source} (sha256 {c.situations.sha256[:12]}).",) if c.situations else ()))  # fmt: skip
    for name, a in c.arms.items():
        none = sum(r.route is None for r in a.records)
        m = a.manifest
        t.add(c.meta([name], len(a.records), n_excluded=none), c.label(name), m.strategy, m.diagnosis, m.policy_sha256, m.clf_mode,
              m.git_dirty, len(a.records), none, ",".join(m.unavailable), a.source)  # fmt: skip
    return t.build()


def _t1_t2(c: _Ctx) -> tuple[Table, Table, PairedDiffCI | None, PairedDiffCI | None]:
    t1 = _Builder("t1_rq1_cost", "RQ1 — số chính", "T1 — Chi phí kỳ vọng/ticket (SỐ CHÍNH RQ1, không trọng số)",
                  ("arm", "cost", "ci95_lo", "ci95_hi", "n_boot", "n_used", "n_families", "seed"),
                  ("Trung bình COST[gold][pred] trên phần giao của các phương án, ma trận mặc định; đơn vị: một lượt duyệt (§6.1).",
                   "Khoảng 95% = bootstrap theo họ (§6.4). Thủ công, Full-auto: giải tích trên cùng phần giao."))  # fmt: skip
    for name in c.names:
        rs = c.sample[name]
        ci: BootstrapCI | None = family_bootstrap_ci(rs, _cost_stat, n_boot=c.n_boot, seed=c.seed) if rs else None
        t1.add(c.meta([name], len(rs)), c.label(name), ci.point if ci else None, ci.lo if ci else None, ci.hi if ci else None,
               ci.n_boot if ci else None, ci.n_used if ci else None, ci.n_families if ci else None, ci.seed if ci else None)  # fmt: skip
    t2 = _Builder("t2_rq1_cost_diff", "RQ1 — số chính", "T2 — Hiệu chi phí Hybrid − phương án khác (ghép cặp theo họ)",
                  ("comparison", "diff", "ci95_lo", "ci95_hi", "contains_zero", "n_boot", "n_used", "n_families", "reading"),
                  ("Vế 1 §6.5: khoảng nằm hẳn dưới 0 → Hybrid rẻ hơn. Khoảng chứa 0 → chưa đủ bằng chứng khác biệt.",))  # fmt: skip
    diffs: dict[str, PairedDiffCI | None] = {}
    for other in ("rule_only", "llm_only"):
        names = ["hybrid", other]
        ok = all(n in c.sample for n in names) and bool(c.sample.get("hybrid"))
        d = paired_family_bootstrap_diff(c.sample["hybrid"], c.sample[other], _cost_stat, n_boot=c.n_boot, seed=c.seed) if ok else None
        diffs[other] = d
        reading = {PASS: "Hybrid rẻ hơn (khoảng nằm hẳn dưới 0)", FAIL: "Hybrid đắt hơn (khoảng nằm hẳn trên 0)",
                   NO_DIFF: NO_DIFF, UNKNOWN: "thiếu phương án hoặc phần giao rỗng"}[_cost_status(d)]  # fmt: skip
        meta = c.meta([n for n in names if n in c.arms] or ["hybrid"], len(c.sample.get("hybrid", ())))
        t2.add(meta, f"Hybrid − {c.label(other)}", d.point if d else None, d.lo if d else None, d.hi if d else None,
               d.contains_zero if d else None, d.n_boot if d else None, d.n_used if d else None, d.n_families if d else None, reading)  # fmt: skip
    return t1.build(), t2.build(), diffs["rule_only"], diffs["llm_only"]


_SCOPES: Final[tuple[tuple[str, Hidden], ...]] = (("tất cả", "all"), ("hidden_factor = true", "only"), ("hidden_factor ≠ true", "except"))


def _t3a(c: _Ctx) -> tuple[Table, SituationFnr | None]:
    notes = [
        ("§6.1: #(tình huống cần người có ít nhất một câu pred = AUTO) / #(tình huống cần người). Cận trên một phía 95% = Clopper–Pearson "
        "(`decision_math`); khoảng hai phía 95% kèm theo. Trên phần giao của các phương án."),
        f"Đơn vị: {c.unit_label}.",
    ]
    if c.mapping is None:
        notes.insert(0, NO_MAPPING_WARNING)
    if not any(r.hidden_factor is not None for r in c.ref.records):
        notes.append("hidden_factor = null ở mọi lá (V11-Q1): dòng `hidden_factor = true` rỗng, dòng `≠ true` = toàn bộ.")
    t = _Builder("t3a_safety_situation", "RQ1 — số chính", "T3a — An toàn: FNR theo tình huống",
                 ("arm", "scope", "unit", "n_situations", "k_missed", "fnr", "upper95_1sided", "ci95_lo", "ci95_hi", "n_mixed_gold"), notes)
    unit_of = c.unit_of()
    own: SituationFnr | None = None
    for name in c.names:
        scopes = [(label, hidden, False) for label, hidden in _SCOPES]
        scopes += [("lớp LLM (decided_by = llm)", "all", True)] if name in LLM_ARMS else []
        for label, hidden, only_llm in scopes:
            f = situation_fnr(c.sample[name], unit_of, only_llm=only_llm, hidden=hidden)
            t.add(c.meta([name], f.n_leaves), c.label(name), label, c.unit_label, f.n, f.k, f.value, f.upper95, f.lo95, f.hi95, f.n_mixed)
    if "hybrid" in c.rq1:  # vế 2 §6.5: trên tình huống đi qua lớp LLM của chính Hybrid (toàn bộ ca tới M5, không giao với phương án khác)
        own = situation_fnr(c.rq1["hybrid"].records, unit_of, only_llm=True)
        t.add(c.meta(["hybrid"], own.n_leaves), c.label("hybrid"), "lớp LLM, toàn bộ ca tới M5 của Hybrid (dùng cho vế 2 §6.5)",
              c.unit_label, own.n, own.k, own.value, own.upper95, own.lo95, own.hi95, own.n_mixed)  # fmt: skip
    return t.build(), own


def _t3b(c: _Ctx) -> Table:
    t = _Builder("t3b_safety_leaf", "RQ1 — số chính", "T3b — An toàn và quyết định theo câu (phụ)",
                 ("arm", "fnr_leaf_k", "fnr_leaf_n", "fnr_leaf", "fnr_leaf_upper95", "fpr", "accuracy", "macro_f1", "escalation_raw_all_leaves"),
                 (("FNR theo câu (phụ), FPR, accuracy 3 lớp, macro-F1 trên phần giao. `escalation_raw_all_leaves` = tỉ lệ lá có exit_code trên "
                  "MỌI lá của file (điểm log 8, §6.2); Thủ công, Full-auto không có."),))  # fmt: skip
    for name in c.names:
        rs = c.sample[name]
        s = safety(rs) if rs else None
        esc = efficiency(c.arms[name].records).escalation.value if name in c.arms else None
        t.add(c.meta([name], len(rs)), c.label(name), s.fnr.k if s else None, s.fnr.n if s else None, s.fnr.value if s else None,
              s.fnr_upper95 if s else None, s.fpr.value if s else None, s.accuracy.value if s else None, s.macro_f1 if s else None, esc)  # fmt: skip
    return t.build()


def _t4(c: _Ctx, d_rule: PairedDiffCI | None, d_llm: PairedDiffCI | None, own: SituationFnr | None) -> tuple[Table, Rq1Verdict]:
    v = rq1_verdict(d_rule, d_llm, own)
    notes = ["Tiêu chí §6.5: Hybrid tốt hơn khi CẢ HAI vế đạt. Không đạt vế nào thì báo trung thực vế đó."]
    if c.mapping is None:
        notes.insert(0, NO_MAPPING_WARNING)
    t = _Builder("t4_rq1_verdict", "RQ1 — số chính", "T4 — Kết luận RQ1 (P8 §6.5)", ("criterion", "value", "bound", "status"), notes)
    meta = c.meta([n for n in ("hybrid", "rule_only", "llm_only") if n in c.arms] or [c.base_name], len(c.sample.get("hybrid", ())))
    for label, d, status in (("vế 1: hiệu chi phí Hybrid − Chỉ-luật (cận trên khoảng 95%)", d_rule, v.cost_vs_rule),
                             ("vế 1: hiệu chi phí Hybrid − Chỉ-LLM (cận trên khoảng 95%)", d_llm, v.cost_vs_llm)):  # fmt: skip
        t.add(meta, label, d.hi if d else None, 0.0, status)
    t.add(meta, "vế 2: cận trên một phía 95% của FNR theo tình huống, lớp LLM của Hybrid", own.upper95 if own else None,
          SAFETY_UPPER_LIMIT, v.safety)  # fmt: skip
    t.add(meta, "kết luận", None, None, v.overall)
    return t.build(), v


def _t5(c: _Ctx) -> Table:
    t = _Builder("t5_operating_mix", "Số phụ", "T5 — Chi phí và route có trọng số (SỐ PHỤ)",
                 ("arm", "mix", "cost_weighted", "automation", "review", "l2", "missing_groups"),
                 (("SỐ PHỤ — số chính RQ1 là chi phí không trọng số (T1). Σ_g mix[g]·(chỉ số trong nhóm gold g); mix chính 70/20/10, độ nhạy "
                  "60/30/10 và 80/15/5. Nhóm gold rỗng → n/a (không chuẩn hoá lại)."),))  # fmt: skip
    for name in c.names:
        rs = c.sample[name]
        om = operating_metrics(rs) if rs else None
        for label, pt in ((("70/20/10 (chính)", om.main),) + tuple(om.sensitivity.items())) if om else ():
            t.add(c.meta([name], len(rs)), c.label(name), label, pt.cost.value, pt.automation.value, pt.review.value, pt.l2.value,
                  ",".join(pt.cost.missing_groups))  # fmt: skip
    return t.build()


def _t6(c: _Ctx) -> Table:
    t = _Builder("t6_ratio_sensitivity", "Số phụ", "T6 — Độ nhạy tỉ lệ bỏ sót/duyệt 5/10/20 (SỐ PHỤ)",
                 ("arm", "ratio", "t_low_theoretical", "cost", "cost_weighted_70_20_10"),
                 (("`cost` = chi phí không trọng số với ma trận `cost_matrix_for_ratio(ratio)`; `t_low_theoretical` = ngưỡng dưới lý thuyết "
                  "= 1/ratio. Phần giao như T1."),))  # fmt: skip
    for name in c.names:
        rs = c.sample[name]
        for r in BREAKEVEN_RATIOS if rs else ():
            cm = cost_matrix_for_ratio(r)
            om = operating_metrics(rs, cost=cm)
            t.add(c.meta([name], len(rs)), c.label(name), r, t_low_star(cm), om.cost.value, om.main.cost.value)
    return t.build()


def _t7(c: _Ctx) -> Table:
    t = _Builder("t7_breakeven", "Số phụ", "T7 — Điểm hoà vốn r* (lượt duyệt / một ca bỏ sót)",
                 ("pair", "mix", "n_pairs", "n_excluded_a", "n_excluded_b", "fixed_a", "miss_a", "fixed_b", "miss_b", "r_star", "reason",
                  "saving_5", "saving_10", "saving_20"),
                 (("Phương án có lớp LLM (A) so với Thủ công và với Chỉ-luật (B), dưới r* bên có `miss` lớn hơn rẻ hơn. `saving` = cost_B − "
                  "cost_A (dương = A rẻ hơn). Mỗi cặp trên CÙNG phần giao với T1 (lá đã nhãn có route ở mọi phương án RQ1, §5.4): "
                  "`n_pairs` = `n` của T1; ở r = 10 chi phí khớp T1 (không trọng số) và T5 (mix). Thủ công = `manual_baseline` của A trên "
                  "phần giao (= Thủ công của T1, G1-Q1). `n_excluded_a`/`n_excluded_b` = 0 vì đã lọc trước; lá ngoài phần giao ở cột "
                  "`n_excluded`, chi tiết T11. Dòng `không trọng số` là số chính, các mix là số phụ."),))  # fmt: skip
    for name in LLM_ARMS:
        rs = c.sample.get(name)
        if not rs:  # phương án vắng hoặc phần giao rỗng → không dòng (không bịa số)
            continue
        against = [("Thủ công", manual_baseline(rs), name)]
        if "rule_only" in c.sample:
            against.append(("Chỉ-luật", c.sample["rule_only"], "rule_only"))
        for other_label, other, other_name in against:
            for mix_label, mix in MIXES.items():
                be = breakeven(rs, other, mix)
                metas = [name] + ([other_name] if other_name != name else [])
                t.add(c.meta(metas, be.n), f"{c.label(name)} vs {other_label}", mix_label, be.n,
                      be.n_excluded_a, be.n_excluded_b, be.fixed_a, be.miss_a, be.fixed_b, be.miss_b, be.r_star, be.reason,
                      *(be.saving[r] for r in BREAKEVEN_RATIOS))  # fmt: skip
    return t.build()


def _t8(c: _Ctx) -> Table:
    t = _Builder("t8_ablation", "Ablation", "T8 — Ablation (P8 §5.4)", ("ablation", "arm", "cost", "fnr_situation", "fnr_upper95_1sided", "clarification_mean"),
                 (("Bỏ tool = tắt chẩn đoán chủ động (S3). Bỏ RAG ở M5 = biến thể \"không trích đoạn\": chưa có trong hợp đồng predictions "
                  "(xác suất biến thể ghi file riêng `probs.jsonl`, chưa có `offline.py`) nên không có số."),))  # fmt: skip
    rows = (("Hybrid đầy đủ", "hybrid"), ("bỏ lớp luật (= Chỉ-LLM)", "llm_only"), ("bỏ lớp LLM (= Chỉ-luật)", "rule_only"),
            ("bỏ tool (tắt chẩn đoán chủ động, S3)", NO_TOOL), ("bỏ RAG ở M5 (biến thể không trích đoạn)", ""))  # fmt: skip
    for label, name in rows:
        arm = c.arms.get(name)
        if arm is None:
            t.add(c.meta([c.base_name], 0, n_excluded=0), label, "không có dữ liệu", None, None, None, None)
            continue
        rs = c.restrict(arm.records)
        f = situation_fnr(rs, c.unit_of())
        t.add(c.meta([name], len(rs)), label, c.label(name), _cost_stat(rs) if rs else None, f.value, f.upper95,
              efficiency(rs).clarification.value if rs else None)  # fmt: skip
    return t.build()


def _t9(c: _Ctx) -> Table:
    t = _Builder("t9_decided_by_calibration", "Hiệu chỉnh", "T9 — decided_by, ECE, Brier",
                 ("arm", "rule_share", "llm_share", "missing_share", "n_cal_raw", "p_method", "ece_raw", "brier_raw", "n_cal_calibrated",
                  "ece_calibrated", "brier_calibrated"),
                 (("ECE (10 bin) và Brier chỉ trên ca decided_by = llm có xác suất; trước = raw_prob, sau = calibrated_prob. calibrated_prob "
                  "= null ở bản chưa hiệu chỉnh (D-38) → n/a. Trên phần giao; chưa gộp 5 phần đo (fold = null ở lượt stack)."),))  # fmt: skip
    for name in RQ1_STRATEGIES:
        rs = c.sample.get(name)
        if not rs:
            continue
        dist = decided_by_distribution(rs)
        try:
            raw, cal = calibration_scores(rs, "raw"), calibration_scores(rs, "calibrated")
        except ValueError:  # trộn p_method trong một phép tính
            raw = cal = None
        t.add(c.meta([name], len(rs)), c.label(name), dist.rule.value, dist.llm.value, dist.missing.value, raw.n if raw else 0,
              raw.p_method if raw else None, raw.ece if raw else None, raw.brier if raw else None, cal.n if cal else 0,
              cal.ece if cal else None, cal.brier if cal else None)  # fmt: skip
    return t.build()


def _t10(c: _Ctx) -> Table:
    t = _Builder("t10_rq3_by_intent", "RQ3", "T10 — RQ3: chẩn đoán chủ động theo intent (S1 so S3)",
                 ("intent", "n_families", "clarification_on", "clarification_off", "reduction", "ci95_lo", "ci95_hi", "contains_zero",
                  "one_turn_on", "one_turn_off", "route_accuracy_on", "route_accuracy_off"),
                 (("`on` = Hybrid bật chẩn đoán (S1), `off` = tắt (S3). `reduction` = lượt hỏi lại TB (off) − (on), dương = chẩn đoán giảm "
                  "lượt hỏi; khoảng 95% bootstrap ghép cặp theo họ. Tính trên MỌI lá (§6.2), theo `gold_intent`; độ chính xác route trên lá "
                  "đã nhãn có route."),))  # fmt: skip
    s1, s3 = c.rq1.get("hybrid"), c.s3
    if s1 is None or s3 is None:
        t.notes.append("Thiếu lượt S1 (Hybrid bật chẩn đoán) hoặc S3 (tắt chẩn đoán): không có số RQ3.")
        return t.build()
    intents = sorted({r.gold_intent or "(không có gold_intent)" for r in s1.records})
    for intent in ("(tất cả)", *intents):
        def pick(records: Records, intent: str = intent) -> list[PredictionRecord]:
            return [r for r in records if intent == "(tất cả)" or (r.gold_intent or "(không có gold_intent)") == intent]

        on, off = pick(s1.records), pick(s3.records)
        e_on, e_off = efficiency(on), efficiency(off)
        d = paired_family_bootstrap_diff(off, on, lambda rs: efficiency(rs).clarification.value, n_boot=c.n_boot, seed=c.seed)
        unl = sum(r.expected_route is None for r in on)
        meta = c.meta(["hybrid", NO_TOOL], len(on), n_unlabeled=unl, n_excluded=0)
        t.add(meta, intent, d.n_families, e_on.clarification.value, e_off.clarification.value, d.point, d.lo, d.hi, d.contains_zero,
              e_on.one_turn.value, e_off.one_turn.value, safety(on).accuracy.value, safety(off).accuracy.value)  # fmt: skip
    return t.build()


def _t11(c: _Ctx) -> Table:
    t = _Builder("t11_exclusions", "Lá bị loại", "T11 — Lá bị loại khỏi mẫu, theo phương án",
                 ("arm", "n_leaves", "n_unlabeled", "n_route_none", "n_reached_labelled", "n_outside_common", "n_e1_injection_suspected"),
                 (("`route_none` = không tới điểm log 4 (ngoài mẫu số §6.1; với phương án có LLM tính là chuyển L2 chỉ ở bước offline, "
                  "chưa có ở đây). `outside_common` = lá đã nhãn có route nhưng không nằm trong phần giao. E1 = dừng ở B2 do model nghi "
                  "(không tới M5, §5.4)."),))  # fmt: skip
    for name, a in c.arms.items():
        rs = a.records
        reached = [r for r in rs if r.expected_route is not None and r.route is not None]
        t.add(c.meta([name], len(c.restrict(rs))), c.label(name), len(rs), sum(r.expected_route is None for r in rs),
              sum(r.route is None for r in rs), len(reached), sum(r.scenario_id not in c.common for r in reached),
              sum(r.exit_code == "E1" for r in rs))  # fmt: skip
    return t.build()


def build_report(arms: Sequence[Arm], situations: Situations | None = None, *, n_boot: int = BOOTSTRAP_N, seed: int = SEED) -> Report:
    """Dựng toàn bộ bảng từ các lượt chạy đã nạp (`load_arm`). Kiểm chéo trước (`check_arms`); thiếu phương án thì bảng liên quan ghi
    `n/a`/"không có dữ liệu", không bịa số."""
    c = _Ctx(arms, situations, n_boot, seed)
    t1, t2, d_rule, d_llm = _t1_t2(c)
    t3a, own = _t3a(c)
    t4, verdict = _t4(c, d_rule, d_llm, own)
    tables = (_t0(c), t1, t2, t3a, _t3b(c), t4, _t5(c), _t6(c), _t7(c), _t8(c), _t9(c), _t10(c), _t11(c))
    warnings: list[str] = []
    if c.n_unlabeled:
        warnings.append(f"n_unlabeled = {c.n_unlabeled}/{len(c.ref.records)} lá chưa nhãn (expected_route null): bỏ qua ở mọi chỉ số cần gold.")
    if not c.common:
        warnings.append("Phần giao rỗng (không lá đã nhãn nào có route ở mọi phương án): các bảng trên phần giao không có số.")
    if c.mapping is None:
        warnings.append(NO_MAPPING_WARNING)
    elif c.situations is not None and (unused := len(c.situations.mapping.keys() - {r.scenario_id for r in c.ref.records})):
        warnings.append(f"situations: {unused} ánh xạ không khớp scenario_id nào của dữ liệu (bỏ qua).")
    if len({a.manifest.git_commit for a in arms}) > 1:
        warnings.append("Các lượt chạy khác git_commit (P8 §5.5 yêu cầu cùng tag).")
    if len({a.manifest.policy_sha256 for a in arms}) > 1:
        warnings.append("Các lượt chạy khác policy_sha256 (P8 §5.5 yêu cầu cùng bản luật).")
    if any(r.fold is None for r in c.ref.records):
        warnings.append("fold = null ở lượt stack (V11-Q3): số liệu chưa gộp theo 5 phần đo, calibrator/ngưỡng từng phần chưa có.")
    if c.s3 is None:
        warnings.append("Không có lượt S3 (Hybrid tắt chẩn đoán): bảng RQ3 và dòng ablation `bỏ tool` rỗng.")
    missing = [LABEL[n] for n in ("rule_only", "llm_only", "hybrid") if n not in c.rq1]
    if missing:
        warnings.append(f"Thiếu phương án {', '.join(missing)}: kết luận RQ1 không đủ vế.")
    mixed = max((situation_fnr(c.sample[n], c.unit_of()).n_mixed for n in c.names), default=0)
    if mixed:
        warnings.append(f"{mixed} đơn vị ({c.unit_label}) có nhãn gold lẫn AUTO và không-AUTO — kiểm ánh xạ tình huống/nhãn.")
    return Report(tuple(a.manifest.run_id for a in arms), tuple(warnings), tables, verdict)


# ---- định dạng và ghi file ---------------------------------------------------------------------------------------------


def _fmt(v: Cell, *, md: bool, col: str = "") -> str:
    if v is None:
        return "n/a" if md else ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.4f}" if md else f"{v:.6f}"
    if md and col == "dataset_sha256":
        return str(v)[:12]
    return str(v).replace("|", "\\|").replace("\n", " ") if md else str(v)


def render_markdown(report: Report) -> str:
    out = ["# Báo cáo M8 — RQ1, RQ3 (P8 v1.4)", "", f"run_id: {', '.join(report.run_ids)}", ""]
    if report.warnings:
        out += ["## Cảnh báo", "", *[f"- {w}" for w in report.warnings], ""]
    section = ""
    for t in report.tables:
        if t.section != section:
            section = t.section
            out += [f"## {section}", ""]
        out += [f"### {t.title}", "", *[f"- {n}" for n in t.notes], ""] if t.notes else [f"### {t.title}", ""]
        out += ["| " + " | ".join(t.columns) + " |", "|" + "---|" * len(t.columns)]
        out += ["| " + " | ".join(_fmt(v, md=True, col=col) for v, col in zip(row, t.columns, strict=True)) + " |" for row in t.rows]
        out.append("")
    return "\n".join(out)


def render_csv(table: Table) -> str:
    class _Sink:
        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, s: str) -> int:
            self.parts.append(s)
            return len(s)

    sink = _Sink()
    w = csv.writer(sink, lineterminator="\n")
    w.writerow(table.columns)
    for row in table.rows:
        w.writerow([_fmt(v, md=False) for v in row])
    return "".join(sink.parts)


def report_files(report: Report) -> dict[str, str]:
    """Tên file → nội dung: `report.md` và một `<key>.csv` cho mỗi bảng."""
    return {"report.md": render_markdown(report), **{f"{t.key}.csv": render_csv(t) for t in report.tables}}


def write_report(report: Report, out_dir: Path) -> list[str]:
    """Ghi `report.md` + CSV từng bảng vào `out_dir` (tạo nếu chưa có). Đã có file trùng tên → `ValueError` (không ghi đè)."""
    files = report_files(report)
    if any((out_dir / name).exists() for name in files):
        raise ValueError("--out đã có file báo cáo của lượt trước — chọn thư mục khác")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    return list(files)


# ---- CLI ---------------------------------------------------------------------------------------------------------------


class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _ArgError(message)


def main(argv: Sequence[str], *, out: Callable[[str], None] = print) -> int:
    parser = _Parser(prog="python -m app.eval.report", description="Bảng báo cáo M8 (P8 v1.4) từ predictions.jsonl + manifest.json")
    parser.add_argument("--arm", action="append", nargs=2, metavar=("PREDICTIONS", "MANIFEST"), default=[],
                        help="một lượt chạy (lặp cho mỗi phương án, thêm S3 nếu có)")  # fmt: skip
    parser.add_argument("--situations", type=Path, help="CSV/JSON scenario_id → situation_id (đơn vị tình huống của FNR)")
    parser.add_argument("--out", type=Path, required=True, help="thư mục MỚI cho report.md và các CSV")
    parser.add_argument("--n-boot", type=int, default=BOOTSTRAP_N)
    parser.add_argument("--seed", type=int, default=SEED)
    try:
        args = parser.parse_args(argv)
        if not args.arm:
            raise ValueError("cần ít nhất một --arm")
        arms = [load_arm(Path(p), Path(m)) for p, m in args.arm]
        situations = load_situations(args.situations) if args.situations else None
        report = build_report(arms, situations, n_boot=args.n_boot, seed=args.seed)
        written = write_report(report, args.out)
    except (_ArgError, ValueError) as e:
        out(f"DỪNG: {e}")
        return 2
    for w in report.warnings:
        out(w)
    out(f"verdict: {report.verdict.overall}")
    out("files: " + " ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
