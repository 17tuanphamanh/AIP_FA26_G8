"""Thu thập RQ2 trên các lá đi lớp LLM của S1: (b) đọc phiếu, (a) gọi thêm `b14_risk_estimate`, (c) tuỳ chọn — một dòng/lá.

Lá được lấy từ `predictions.jsonl` của S1 (hợp đồng v1.1): `decided_by = "llm"`, `p_method = "sampling_k5"`, có `raw_prob`, đã nhãn.
Phần (fold) lấy từ `eval/folds.csv` (D-58) theo họ — họ không có trong file → `ValueError` (không đoán).

(c): lá ĐẦU TIÊN có phản hồi là lời gọi kiểm khả thi (`check_logprobs_feasible`); không khả thi → dừng (c) cho cả run, bằng chứng vào
manifest, KHÔNG dòng nào có khoá `p_c`. `BudgetStop` → dừng (c) (và (a) do gateway tự chặn bằng trần `--max-usd`).
Lá có model của dòng phiếu S1 ≠ model đang cấu hình → không gọi (a)/(c) cho lá đó (`model_mismatch`).
"""

import csv
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.eval.predictions import PredictionRecord
from app.eval.rq2.logprob import (
    BudgetStop,
    Feasibility,
    LogprobClient,
    LogprobHttpError,
    RequestCfg,
    check_logprobs_feasible,
    decisive_p,
)
from app.eval.rq2.self_report import self_report
from app.eval.rq2.source import (
    Rejected,
    fetch_cache,
    fetch_vote_calls,
    rebuild,
    sample_index,
)
from app.eval.rq2.votes import p_from_votes, vote_key
from app.eval.stack import Sql
from app.llm.ports import LlmPort
from app.llm.registry import Prompt


@dataclass(frozen=True)
class Leaf:
    ticket_id: str
    scenario_id: str
    family: str
    fold: int
    y: bool
    audit_raw: float


def load_folds(path: Path) -> dict[str, int]:
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    if not rows or set(rows[0]) != {"family", "fold"}:
        raise ValueError("folds.csv: cần đúng 2 cột family, fold")
    out: dict[str, int] = {}
    for r in rows:
        if r["family"] in out:
            raise ValueError("folds.csv: họ trùng")
        out[r["family"]] = int(r["fold"])
    return out


def leaves(records: Sequence[PredictionRecord], folds: Mapping[str, int]) -> list[Leaf]:
    out = []
    for r in records:
        if r.decided_by != "llm" or r.raw_prob is None or r.expected_route is None:
            continue
        if r.p_method != "sampling_k5":
            raise ValueError("S1: p_method của lá đi lớp LLM phải là sampling_k5 (bản đo)")
        if r.family not in folds:
            raise ValueError("họ của lá không có trong folds.csv")
        out.append(Leaf(r.ticket_id, r.scenario_id, r.family, folds[r.family], r.expected_route != "AUTO", r.raw_prob))
    return out


@dataclass
class CRun:
    client: LogprobClient
    cfg: RequestCfg
    wire: Callable[[list[dict[str, str]]], list[dict[str, str]]]  # biến đổi messages của provider (json_object)
    status: str = "unchecked"  # unchecked | feasible | infeasible | budget_stop
    feasibility: Feasibility | None = None


@dataclass
class Deps:
    sql: Sql
    vote_prompt: Prompt
    budget_in: int
    model_version: str | None  # roles.strong.model_version của cấu hình (khoá cache phiếu)
    model: str | None = None  # model đang cấu hình cho (a)/(c); None = không gọi (a)/(c)
    llm: LlmPort | None = None
    c: CRun | None = None
    allow_audit: bool = False
    counts: Counter[str] = field(default_factory=Counter)
    s1_models: Counter[str] = field(default_factory=Counter)


async def _c(deps: Deps, row: dict[str, Any], messages: list[dict[str, str]]) -> None:
    c = deps.c
    assert c is not None
    if c.status == "infeasible":
        return
    if c.status == "budget_stop":
        row["p_c"], row["reasons"]["c"] = None, "budget"
        return
    try:
        resp = await c.client.fetch(c.cfg.body(c.wire(messages)))
    except BudgetStop:
        c.status = "budget_stop"
        row["p_c"], row["reasons"]["c"] = None, "budget"
        return
    except LogprobHttpError as e:
        row["reasons"]["c"] = f"http_{e.status}"
        row["p_c"] = None
        return
    if c.status == "unchecked":
        c.feasibility = check_logprobs_feasible(resp)
        c.status = "feasible" if c.feasibility.ok else "infeasible"
        if not c.feasibility.ok:
            return
    d = decisive_p(resp)
    row["p_c"] = d.p
    row["reasons"]["c"] = d.reason
    if d.p is not None and (d.n_true == 0 or d.n_false == 0):
        deps.counts["c_one_class_in_top"] += 1


async def collect_leaf(deps: Deps, leaf: Leaf) -> dict[str, Any]:
    calls = fetch_vote_calls(deps.sql, leaf.ticket_id)
    for c in calls:
        deps.s1_models[c.model] += 1
    keys = [vote_key(c, model_version=deps.model_version) for c in calls if c.prompt_full is not None]
    vr = p_from_votes(calls, fetch_cache(deps.sql, keys), leaf.audit_raw, model_version=deps.model_version,
                      allow_audit=deps.allow_audit)  # fmt: skip
    row: dict[str, Any] = {
        "ticket_id": leaf.ticket_id, "scenario_id": leaf.scenario_id, "family": leaf.family, "fold": leaf.fold, "y": leaf.y,
        "p_b": vr.p_b, "p_b_source": vr.source, "votes": list(vr.votes) if vr.votes is not None else None, "p_a": None,
        "a_trimmed_evidence": None, "reasons": {"a": None, "b": vr.reason},
    }  # fmt: skip
    mismatch = deps.model is not None and any(c.model != deps.model for c in calls)
    try:
        inp = rebuild(leaf.ticket_id, calls, deps.vote_prompt, budget_in=deps.budget_in)
    except Rejected as e:
        row["reasons"]["a"] = e.reason
        inp = None
    if deps.llm is None:
        row["reasons"]["a"] = row["reasons"]["a"] or "not_run"
    elif inp is not None and mismatch:
        row["reasons"]["a"] = "model_mismatch"
    elif inp is not None:
        sr = await self_report(deps.llm, inp.variables)
        row["p_a"], row["a_trimmed_evidence"], row["reasons"]["a"] = sr.p_a, sr.trimmed_evidence, sr.error
    if deps.c is not None:
        row["reasons"]["c"] = None
        zero = [c for c in calls if c.prompt_full is not None and _idx(deps.vote_prompt, c) == 0]
        if mismatch:
            row["p_c"], row["reasons"]["c"] = None, "model_mismatch"
        elif len(calls) != 5 or len(zero) != 1 or any(c.error for c in calls):
            row["p_c"], row["reasons"]["c"] = None, "vote_calls"
        else:
            await _c(deps, row, zero[0].messages)
    return row


def _idx(prompt: Prompt, call: Any) -> int | None:
    try:
        return sample_index(prompt, call)
    except Rejected:
        return None


async def collect(deps: Deps, items: Sequence[Leaf]) -> list[dict[str, Any]]:
    rows = [await collect_leaf(deps, leaf) for leaf in items]
    c = deps.c
    if c is not None and c.status not in ("feasible", "budget_stop"):
        for r in rows:  # không khả thi / chưa kiểm được → không có cột p_c giả
            r.pop("p_c", None)
            r["reasons"].pop("c", None)
    for r in rows:
        for m, reason in r["reasons"].items():
            deps.counts[f"{m}:{reason or 'ok'}"] += 1
    return rows


def c_summary(c: CRun | None) -> dict[str, Any]:
    if c is None:
        return {"status": "not_run"}
    out: dict[str, Any] = {"status": c.status, "network_calls": c.client.network_calls, "cache_hits": c.client.cache_hits}
    if c.feasibility is not None:
        out["feasibility"] = asdict(c.feasibility)
    if c.status == "infeasible":
        out["note"] = "(c) không khả thi — bằng chứng ở feasibility.evidence; không suy p từ nguồn khác"
    return out
