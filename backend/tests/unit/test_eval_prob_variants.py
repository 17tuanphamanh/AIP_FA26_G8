"""G10 — `scripts/eval/prob_variants.py`: ba biến thể xác suất thô (P8 v1.4 §5.4 dòng "Biến thể xác suất (offline, script)", §5.6).

Kỳ vọng chép từ P8 v1.4 + quyết định duyệt mẫu A, không suy từ code:
- `with_evidence` = `raw_prob` đã ghi ở stack; `no_evidence` = `estimate(action, ctx, [])`; `max` = max của hai, trên xác suất THÔ,
  chỉ khi có đủ hai biến thể.
- Ca có `kb_gap` ở stack: `no_evidence` CHÉP `raw_prob`, không gọi lại. Lỗi gọi `no_evidence`: bỏ `no_evidence` + `max` của ca đó.
- `probs.jsonl`: đúng 3 trường `scenario_id`, `variant`, `raw_prob` (§5.6); mỗi lượt một file; không đổi hợp đồng.
- `compare`: fit Platt CHỈ trên `calibration`, đo trên `test`; lẫn → `LeakageError`; không chọn biến thể.

LLM giả: `LlmRiskEstimator` + gateway + `ScriptedLLM` (đường thật của estimator) và estimator giả ghi lại lời gọi. Dữ liệu tổng hợp;
không đọc kịch bản/KB/`.env`.
"""

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from app.core.errors import LLMSchemaError, LLMUnavailable
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.risk.calibrator import LabeledSample, LeakageError, fit_platt
from app.risk.decision_math import brier, ece
from app.risk.estimator import LlmRiskEstimator, RiskEstimate, estimator_vars
from app.risk.models import RiskContext
from tests.fakes.llm import make_gateway
from tests.fakes.scripted_llm import Reply, Script, Step
from tests.unit._b2review import load_script

SCRIPT = "scripts/eval/prob_variants.py"
REPO = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)

ESTIMATE_OK: dict[str, Any] = {"prob_needs_human": 0.42, "factors": ["target_is_other"], "rationale": "ổn"}
VOTES = [True, True, False, True, False]  # → 0,6


@pytest.fixture
def pv(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load_script(SCRIPT, monkeypatch)


# ---- dữ liệu tổng hợp --------------------------------------------------------------------------------------------------


def _action() -> Action:
    return Action(
        type="renew_vpn_cert", target="device:LAP-0342", requested_for="nv001", scope="single_device",
        privilege_level="standard_user", reversible=True, reversibility="full", data_sensitivity="low",
        params={"device_id": "LAP-0342"},
        facts={"device_registered": True, "device_owner_is_requester": True, "cert_status": "expired"},
    )  # fmt: skip


def _ctx() -> RiskContext:
    requester = RequesterContext(
        user_id="nv001", role="employee", department="finance", manager_id="ql007", employment_status="active",
        tenure_days=400, is_privileged_account=False, captured_at=NOW,
    )  # fmt: skip
    return RiskContext(requester=requester, facts={"device_registered": True}, now=NOW, within_business_hours=True,
                       target_is_other=False)  # fmt: skip


def _chunk() -> Any:
    from app.domain.ticket_state import ChunkRef

    return ChunkRef(chunk_id="KB-VPN-004#0", doc_id="KB-VPN-004", version=1, seq=0, title="Tiêu đề",
                    heading_path="Gia hạn > Bước 0", score=0.8, excerpt="trích-đoạn-0")  # fmt: skip


def rec(pv: ModuleType, sid: str, *, split: str = "calibration", gold: str = "HITL", p: float = 0.5, kb: bool = False,
        family: str | None = None) -> Any:
    return pv.RecordedCase(scenario_id=sid, family=family or f"F-{sid}", split=split, gold_route=gold, raw_prob=p, kb_gap=kb)


def dataset(pv: ModuleType, *, flip_test: bool = False, flip_cal: tuple[int, ...] = ()) -> list[Any]:
    """24 ca calibration (raw tăng dần, nhãn gần đơn điệu) + 4 ca test tính tay: raw .9/.1/.8/.2, nhãn 1/0/0/0."""
    out = []
    for i in range(24):
        positive = (i >= 12) != (i in (3, 14))
        positive = positive != (i in flip_cal)
        out.append(rec(pv, f"c{i:02d}", gold="HITL" if positive else "AUTO", p=round(0.05 + 0.04 * i, 2)))
    test = [(0.9, True), (0.1, False), (0.8, False), (0.2, False)]
    for j, (p, positive) in enumerate(test):
        positive = positive != flip_test
        out.append(rec(pv, f"t{j}", split="test", gold="HITL" if positive else "AUTO", p=p))
    return out


def ok(pv: ModuleType, sid: str, p: float) -> Any:
    return pv.WithoutRow(scenario_id=sid, raw_prob=p)


def fail(pv: ModuleType, sid: str, name: str = "LLMUnavailable") -> Any:
    return pv.WithoutRow(scenario_id=sid, error=name)


def full_without(pv: ModuleType, recorded: Sequence[Any]) -> list[Any]:
    """no_evidence = raw·0,8 + 0,1 (đơn điệu tăng) cho mọi ca không kb_gap."""
    return [ok(pv, r.scenario_id, round(r.raw_prob * 0.8 + 0.1, 4)) for r in recorded if not r.kb_gap]


def by_variant(res: Any) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in res.rows:
        out.setdefault(row.variant, {})[row.scenario_id] = row.raw_prob
    return out


# ---- estimator giả ghi lại lời gọi -------------------------------------------------------------------------------------


class ScriptedEstimator:
    """Thoả `RiskEstimator`: kết quả theo thứ tự lời gọi (số hoặc ngoại lệ); ghi (action, ctx, retrieved)."""

    def __init__(self, results: Sequence[float | BaseException]) -> None:
        self._results = list(results)
        self.calls: list[tuple[Action, RiskContext, list[Any]]] = []

    async def estimate(self, action: Action, ctx: RiskContext, retrieved: Sequence[Any]) -> RiskEstimate:
        self.calls.append((action, ctx, list(retrieved)))
        r = self._results.pop(0)
        if isinstance(r, BaseException):
            raise r
        return RiskEstimate(r, "self_report", (), "b14_risk_estimate", "1", "gia")


def cases_for(pv: ModuleType, recorded: Sequence[Any]) -> dict[str, Any]:
    return {r.scenario_id: pv.CollectCase(scenario_id=r.scenario_id, action=_action(), ctx=_ctx()) for r in recorded}


# ---- collect_no_evidence ----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_self_report_sends_empty_evidence_rest_unchanged(pv: ModuleType) -> None:
    """Lần gọi B14 mới có `evidence == []`; `intended_action`, `risk_context` giống hệt lần có trích đoạn."""
    gw = make_gateway({"b14_risk_estimate": [Reply(ESTIMATE_OK)]})
    estimator = LlmRiskEstimator(gw.client, p_method="self_report", eval_mode=True)
    recorded = [rec(pv, "a")]
    rows = await pv.collect_no_evidence(estimator, recorded, cases_for(pv, recorded))
    assert [(r.scenario_id, r.raw_prob, r.error) for r in rows] == [("a", 0.42, None)]
    (call,) = gw.llm.calls
    sent = dict(call.variables)
    assert sent["evidence"] == []
    with_evidence = estimator_vars(_action(), _ctx(), [_chunk()])
    assert with_evidence["evidence"] != []
    assert {k: v for k, v in sent.items() if k != "evidence"} == {k: v for k, v in with_evidence.items() if k != "evidence"}


@pytest.mark.asyncio
async def test_collect_k5_five_votes_all_empty_evidence(pv: ModuleType) -> None:
    def votes(variables: Mapping[str, Any]) -> Step:
        return Reply({"needs_human": VOTES[int(variables["sample_idx"])], "factors": []})

    scripts: dict[str, Script] = {"b14_risk_vote": votes}
    gw = make_gateway(scripts)
    estimator = LlmRiskEstimator(gw.client, p_method="sampling_k5", eval_mode=True)
    recorded = [rec(pv, "a")]
    rows = await pv.collect_no_evidence(estimator, recorded, cases_for(pv, recorded))
    assert rows[0].raw_prob == pytest.approx(0.6, abs=1e-12)
    calls = gw.llm.calls_for("b14_risk_vote")
    assert len(calls) == 5 and all(c.variables["evidence"] == [] for c in calls)


@pytest.mark.asyncio
async def test_collect_estimator_receives_empty_retrieved_list(pv: ModuleType) -> None:
    est = ScriptedEstimator([0.3, 0.4])
    recorded = [rec(pv, "a"), rec(pv, "b")]
    await pv.collect_no_evidence(est, recorded, cases_for(pv, recorded))
    assert [c[2] for c in est.calls] == [[], []]
    assert all(c[0] == _action() and c[1] == _ctx() for c in est.calls)


@pytest.mark.asyncio
async def test_collect_kb_gap_case_is_never_called_and_needs_no_input(pv: ModuleType) -> None:
    est = ScriptedEstimator([0.3])
    recorded = [rec(pv, "a", kb=True), rec(pv, "b")]
    cases = cases_for(pv, [recorded[1]])  # ca kb_gap không cần đầu vào
    rows = await pv.collect_no_evidence(est, recorded, cases)
    assert [r.scenario_id for r in rows] == ["b"]
    assert len(est.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [LLMUnavailable("x"), LLMSchemaError("x")])
async def test_collect_recoverable_error_becomes_error_row_and_run_continues(pv: ModuleType, exc: BaseException) -> None:
    est = ScriptedEstimator([0.3, exc, 0.5])
    recorded = [rec(pv, "a"), rec(pv, "b"), rec(pv, "c")]
    rows = await pv.collect_no_evidence(est, recorded, cases_for(pv, recorded))
    assert [(r.scenario_id, r.raw_prob, r.error) for r in rows] == [
        ("a", 0.3, None), ("b", None, type(exc).__name__), ("c", 0.5, None),
    ]  # fmt: skip
    assert len(est.calls) == 3


@pytest.mark.asyncio
async def test_collect_unexpected_error_is_a_bug_and_propagates(pv: ModuleType) -> None:
    est = ScriptedEstimator([RuntimeError("bug")])
    recorded = [rec(pv, "a")]
    with pytest.raises(RuntimeError):
        await pv.collect_no_evidence(est, recorded, cases_for(pv, recorded))


@pytest.mark.asyncio
async def test_collect_missing_input_fails_before_any_call(pv: ModuleType) -> None:
    est = ScriptedEstimator([0.3, 0.4])
    recorded = [rec(pv, "a"), rec(pv, "b")]
    with pytest.raises(pv.DataError):
        await pv.collect_no_evidence(est, recorded, cases_for(pv, recorded[:1]))
    assert est.calls == []


@pytest.mark.asyncio
async def test_collect_duplicate_recorded_rejected(pv: ModuleType) -> None:
    est = ScriptedEstimator([0.3])
    with pytest.raises(pv.DataError):
        await pv.collect_no_evidence(est, [rec(pv, "a"), rec(pv, "a")], cases_for(pv, [rec(pv, "a")]))
    assert est.calls == []


# ---- build_probs -----------------------------------------------------------------------------------------------------


def test_build_three_variants_and_max_is_max_of_raw(pv: ModuleType) -> None:
    recorded = [rec(pv, "a", p=0.7), rec(pv, "b", p=0.2), rec(pv, "c", p=0.5)]
    res = pv.build_probs(recorded, [ok(pv, "a", 0.4), ok(pv, "b", 0.9), ok(pv, "c", 0.5)])
    v = by_variant(res)
    assert v["with_evidence"] == {"a": 0.7, "b": 0.2, "c": 0.5}
    assert v["no_evidence"] == {"a": 0.4, "b": 0.9, "c": 0.5}
    assert v["max"] == {"a": 0.7, "b": 0.9, "c": 0.5}  # with > no, no > with, hoà
    assert (res.n_cases, res.n_copied, res.failed, res.n_missing) == (3, 0, {}, 0)


def test_build_kb_gap_copies_with_evidence_and_counts(pv: ModuleType) -> None:
    recorded = [rec(pv, "a", p=0.7, kb=True), rec(pv, "b", p=0.2), rec(pv, "c", p=0.4, kb=True)]
    res = pv.build_probs(recorded, [ok(pv, "b", 0.6)])
    v = by_variant(res)
    assert v["no_evidence"] == {"a": 0.7, "b": 0.6, "c": 0.4}
    assert v["max"] == {"a": 0.7, "b": 0.6, "c": 0.4}
    assert res.n_copied == 2


def test_build_error_drops_no_evidence_and_max_but_keeps_with_evidence(pv: ModuleType) -> None:
    recorded = [rec(pv, "a"), rec(pv, "b"), rec(pv, "c"), rec(pv, "d")]
    without = [ok(pv, "a", 0.4), fail(pv, "b"), fail(pv, "c", "LLMSchemaError")]  # d: không có dòng
    res = pv.build_probs(recorded, without)
    v = by_variant(res)
    assert set(v["with_evidence"]) == {"a", "b", "c", "d"}
    assert set(v["no_evidence"]) == set(v["max"]) == {"a"}
    assert res.failed == {"LLMSchemaError": 1, "LLMUnavailable": 1}
    assert res.n_missing == 1


def test_build_rejects_unknown_duplicate_and_kb_gap_called(pv: ModuleType) -> None:
    recorded = [rec(pv, "a"), rec(pv, "k", kb=True)]
    with pytest.raises(pv.DataError):
        pv.build_probs(recorded, [ok(pv, "zzz", 0.1)])
    with pytest.raises(pv.DataError):
        pv.build_probs(recorded, [ok(pv, "a", 0.1), ok(pv, "a", 0.2)])
    with pytest.raises(pv.DataError):
        pv.build_probs(recorded, [ok(pv, "a", 0.1), ok(pv, "k", 0.2)])  # ca kb_gap phải chép, không gọi
    with pytest.raises(pv.DataError):
        pv.build_probs([rec(pv, "a"), rec(pv, "a")], [])


def test_build_rows_sorted_by_scenario_then_variant_and_order_independent(pv: ModuleType) -> None:
    recorded = [rec(pv, s, p=p) for s, p in (("c", 0.3), ("a", 0.6), ("b", 0.1))]
    without = [ok(pv, "c", 0.5), ok(pv, "a", 0.2), ok(pv, "b", 0.9)]
    res1 = pv.build_probs(recorded, without)
    res2 = pv.build_probs(list(reversed(recorded)), list(reversed(without)))
    assert [(r.scenario_id, r.variant) for r in res1.rows] == [
        (s, v) for s in ("a", "b", "c") for v in ("with_evidence", "no_evidence", "max")
    ]  # fmt: skip
    assert res1.rows == res2.rows


# ---- hợp đồng probs.jsonl / đọc-ghi -----------------------------------------------------------------------------------


def test_probs_file_contract_exactly_three_fields_in_order(pv: ModuleType, tmp_path: Path) -> None:
    recorded = dataset(pv)
    res = pv.build_probs(recorded, full_without(pv, recorded))
    path = tmp_path / "S1" / "probs.jsonl"
    pv.write_jsonl(path, res.rows)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n") and "\r" not in text
    for line in text.splitlines():
        obj = json.loads(line)
        assert list(obj) == ["scenario_id", "variant", "raw_prob"]
        assert obj["variant"] in {"with_evidence", "no_evidence", "max"}
        assert 0.0 <= obj["raw_prob"] <= 1.0
    assert pv.load_jsonl(path, pv.ProbRow) == res.rows  # khứ hồi


def test_probs_bytes_identical_for_shuffled_inputs(pv: ModuleType, tmp_path: Path) -> None:
    recorded = dataset(pv)
    without = full_without(pv, recorded)
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    pv.write_jsonl(a, pv.build_probs(recorded, without).rows)
    pv.write_jsonl(b, pv.build_probs(recorded[::-1], without[::-1]).rows)
    assert a.read_bytes() == b.read_bytes()


def test_write_never_overwrites(pv: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "probs.jsonl"
    path.write_text("giữ nguyên\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        pv.write_jsonl(path, [pv.ProbRow(scenario_id="a", variant="max", raw_prob=0.5)])
    assert path.read_text(encoding="utf-8") == "giữ nguyên\n"


@pytest.mark.parametrize(
    "bad",
    [
        {"scenario_id": "a", "variant": "max", "raw_prob": 0.5, "kb_gap": False},  # trường lạ (hợp đồng 3 trường)
        {"scenario_id": "a", "variant": "max"},
        {"scenario_id": "a", "variant": "self_report", "raw_prob": 0.5},  # biến thể ngoài tập
        {"scenario_id": "a", "variant": "max", "raw_prob": 1.0001},
        {"scenario_id": "a", "variant": "max", "raw_prob": -0.1},
        {"scenario_id": "a", "variant": "max", "raw_prob": True},
        {"scenario_id": "", "variant": "max", "raw_prob": 0.5},
    ],
)
def test_prob_row_rejects_contract_violations(pv: ModuleType, bad: dict[str, Any]) -> None:
    with pytest.raises(Exception, match=r"validation|Validation"):
        pv.ProbRow.model_validate_json(json.dumps(bad))


def test_prob_row_rejects_nan(pv: ModuleType) -> None:
    with pytest.raises(Exception, match=r"validation|Validation"):
        pv.ProbRow.model_validate_json('{"scenario_id": "a", "variant": "max", "raw_prob": NaN}')


def test_without_row_needs_exactly_one_of_prob_or_error(pv: ModuleType) -> None:
    with pytest.raises(Exception, match=r"validation|Validation"):
        pv.WithoutRow(scenario_id="a")
    with pytest.raises(Exception, match=r"validation|Validation"):
        pv.WithoutRow(scenario_id="a", raw_prob=0.1, error="LLMUnavailable")


def test_loader_rejects_empty_blank_and_duplicate_free_names_without_echoing_values(pv: ModuleType, tmp_path: Path) -> None:
    empty = tmp_path / "e.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(pv.DataError):
        pv.load_jsonl(empty, pv.RecordedCase)
    blank = tmp_path / "b.jsonl"
    good = pv.RecordedCase(scenario_id="a", family="F", split="test", gold_route="AUTO", raw_prob=0.1, kb_gap=False)
    blank.write_text(good.model_dump_json() + "\n\n", encoding="utf-8")
    with pytest.raises(pv.DataError, match=":2:"):
        pv.load_jsonl(blank, pv.RecordedCase)
    canary = tmp_path / "c.jsonl"
    canary.write_text(json.dumps({**json.loads(good.model_dump_json()), "gold_route": "CANARY-ROUTE-9f3"}) + "\n", encoding="utf-8")
    with pytest.raises(pv.DataError) as ei:
        pv.load_jsonl(canary, pv.RecordedCase)
    assert "CANARY-ROUTE-9f3" not in str(ei.value) and "gold_route" in str(ei.value)


def test_collect_case_roundtrips_action_and_context_json(pv: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    case = pv.CollectCase(scenario_id="a", action=_action(), ctx=_ctx())
    path.write_text(case.model_dump_json() + "\n", encoding="utf-8")
    (back,) = pv.load_jsonl(path, pv.CollectCase)
    assert back.action == _action() and back.ctx == _ctx()


# ---- compare_variants -----------------------------------------------------------------------------------------------


def _reports(pv: ModuleType, recorded: Sequence[Any], without: Sequence[Any] | None = None) -> dict[tuple[str, str], Any]:
    res = pv.build_probs(recorded, full_without(pv, recorded) if without is None else without)
    return {(r.scope, r.variant): r for r in pv.compare_variants(recorded, res.rows, now=NOW)}


def test_compare_raw_metrics_match_hand_computation(pv: ModuleType) -> None:
    """Phần đo raw .9/.1/.8/.2, nhãn 1/0/0/0: Brier = (.01+.01+.64+.04)/4 = .175; ECE = (.1+.1+.8+.2)/4 = .3."""
    rep = _reports(pv, dataset(pv))[("own", "with_evidence")]
    assert rep.raw_brier == pytest.approx(0.175, abs=1e-12)
    assert rep.raw_ece == pytest.approx(0.3, abs=1e-12)
    assert (rep.n_cal, rep.n_test, rep.n_test_pos) == (24, 4, 1)


def test_compare_calibrated_metrics_are_platt_fitted_on_calibration_only(pv: ModuleType) -> None:
    recorded = dataset(pv)
    rep = _reports(pv, recorded)[("own", "with_evidence")]
    cal = [LabeledSample(split="calibration", family=r.family, raw_prob=r.raw_prob, y=r.gold_route != "AUTO")
           for r in recorded if r.split == "calibration"]  # fmt: skip
    calibrator = fit_platt(cal, now=NOW)
    tests = [r for r in recorded if r.split == "test"]
    p = [calibrator.transform(r.raw_prob) for r in tests]
    y = [r.gold_route != "AUTO" for r in tests]
    assert rep.fit == "ok" and rep.calibrator_version == calibrator.params.version
    assert rep.cal_ece == pytest.approx(ece(p, y), abs=1e-12)
    assert rep.cal_brier == pytest.approx(brier(p, y), abs=1e-12)
    assert rep.cal_auc is not None and 0.0 <= rep.cal_auc <= 1.0


def test_compare_calibrator_ignores_test_rows_but_follows_calibration_rows(pv: ModuleType) -> None:
    base = _reports(pv, dataset(pv))[("own", "with_evidence")]
    changed_test = _reports(pv, dataset(pv, flip_test=True))[("own", "with_evidence")]
    changed_cal = _reports(pv, dataset(pv, flip_cal=(0,)))[("own", "with_evidence")]
    assert changed_test.calibrator_version == base.calibrator_version  # đổi nhãn phần đo không đổi calibrator
    assert changed_test.raw_brier != base.raw_brier
    assert changed_cal.calibrator_version != base.calibrator_version


def test_compare_mixed_splits_do_not_raise_leakage(pv: ModuleType) -> None:
    """Dữ liệu có cả calibration lẫn test: `compare_variants` tự tách, không bao giờ đưa mẫu test vào fit."""
    assert _reports(pv, dataset(pv))  # không ném LeakageError


def test_fit_variant_does_not_swallow_leakage(pv: ModuleType) -> None:
    samples = [LabeledSample(split="calibration", family=f"F{i}", raw_prob=0.05 + 0.04 * i, y=i >= 6) for i in range(12)]
    samples.append(LabeledSample(split="test", family="Ft", raw_prob=0.5, y=True))
    with pytest.raises(LeakageError):
        pv.fit_variant(samples, now=NOW)


def test_fit_variant_returns_reason_for_unfittable_data(pv: ModuleType) -> None:
    few = [LabeledSample(split="calibration", family=f"F{i}", raw_prob=0.1 * i, y=i > 2) for i in range(5)]
    one_class = [LabeledSample(split="calibration", family=f"F{i}", raw_prob=0.05 * i, y=True) for i in range(12)]
    assert isinstance(pv.fit_variant(few, now=NOW), str)
    assert isinstance(pv.fit_variant(one_class, now=NOW), str)


def test_compare_unfittable_calibration_reports_reason_and_keeps_raw_metrics(pv: ModuleType) -> None:
    recorded = [r if r.split == "test" else rec(pv, r.scenario_id, gold="HITL", p=r.raw_prob) for r in dataset(pv)]
    rep = _reports(pv, recorded)[("own", "with_evidence")]
    assert rep.fit != "ok" and rep.calibrator_version is None
    assert rep.cal_ece is rep.cal_brier is rep.cal_auc is None
    assert rep.raw_ece is not None and rep.raw_brier is not None


def test_compare_no_test_rows_gives_no_metrics(pv: ModuleType) -> None:
    recorded = [r for r in dataset(pv) if r.split == "calibration"]
    rep = _reports(pv, recorded)[("own", "with_evidence")]
    assert rep.n_test == 0 and rep.raw_ece is None and rep.cal_ece is None and rep.fit == "ok"


def test_compare_auc_undefined_when_test_has_one_class(pv: ModuleType) -> None:
    recorded = [r if r.split == "calibration" else rec(pv, r.scenario_id, split="test", gold="HITL", p=r.raw_prob)
                for r in dataset(pv)]  # fmt: skip
    rep = _reports(pv, recorded)[("own", "with_evidence")]
    assert rep.cal_auc is None and rep.cal_ece is not None


def test_compare_own_vs_common_scope(pv: ModuleType) -> None:
    recorded = dataset(pv)
    without = full_without(pv, recorded)
    without = [fail(pv, "c05") if w.scenario_id == "c05" else w for w in without]
    rep = _reports(pv, recorded, without)
    assert rep[("own", "with_evidence")].n_cal == 24
    assert rep[("own", "no_evidence")].n_cal == rep[("own", "max")].n_cal == 23
    assert {rep[("common", v)].n_cal for v in ("with_evidence", "no_evidence", "max")} == {23}
    assert {rep[("common", v)].n_test for v in ("with_evidence", "no_evidence", "max")} == {4}


def test_compare_max_variant_scored_on_max_values(pv: ModuleType) -> None:
    """no_evidence = raw·.8+.1 ≥ raw khi raw ≤ .5, nhỏ hơn khi raw > .5 → `max` ở phần đo khác cả hai biến thể kia."""
    rep = _reports(pv, dataset(pv))
    assert rep[("own", "max")].raw_brier not in (rep[("own", "with_evidence")].raw_brier, rep[("own", "no_evidence")].raw_brier)


def test_compare_label_is_gold_not_auto(pv: ModuleType) -> None:
    """ESCALATE_L2 và HITL đều là "cần người" (y = True), chỉ AUTO là False."""
    recorded = [rec(pv, "t0", split="test", gold="ESCALATE_L2", p=0.8), rec(pv, "t1", split="test", gold="AUTO", p=0.8),
                *[rec(pv, f"c{i}", gold="AUTO" if i < 6 else "HITL", p=0.05 + 0.04 * i) for i in range(12)]]  # fmt: skip
    rep = _reports(pv, recorded)[("own", "with_evidence")]
    assert rep.n_test_pos == 1 and rep.n_cal_pos == 6


def test_compare_rejects_unknown_or_duplicate_rows(pv: ModuleType) -> None:
    recorded = dataset(pv)
    with pytest.raises(pv.DataError):
        pv.compare_variants(recorded, [pv.ProbRow(scenario_id="zzz", variant="max", raw_prob=0.5)], now=NOW)
    row = pv.ProbRow(scenario_id="c00", variant="max", raw_prob=0.5)
    with pytest.raises(pv.DataError):
        pv.compare_variants(recorded, [row, row], now=NOW)


def test_compare_never_names_a_best_variant(pv: ModuleType) -> None:
    fields = set(pv.VariantReport.__dataclass_fields__)
    assert not {f for f in fields if re.search(r"best|win|choice|chosen|select|pick", f)}
    assert not hasattr(pv, "select_variant") and not hasattr(pv, "best_variant")


# ---- dòng lệnh -------------------------------------------------------------------------------------------------------


def _write_inputs(pv: ModuleType, tmp: Path) -> tuple[Path, Path]:
    recorded = dataset(pv)
    recorded[0] = rec(pv, "c00", gold="AUTO", p=0.05, kb=True)  # một ca kb_gap → chép
    without = [fail(pv, w.scenario_id) if w.scenario_id == "c07" else w for w in full_without(pv, recorded)]
    with_path, without_path = tmp / "with.jsonl", tmp / "without.jsonl"
    pv.write_jsonl(with_path, recorded)
    pv.write_jsonl(without_path, without)
    return with_path, without_path


def test_cli_build_writes_file_and_prints_counts(pv: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with_path, without_path = _write_inputs(pv, tmp_path)
    out = tmp_path / "S1" / "probs.jsonl"
    assert pv.main(["build", str(with_path), str(without_path), str(out)]) == 0
    said = capsys.readouterr().out
    assert "ca đi lớp LLM: 28" in said
    assert "(không gọi lại): 1" in said  # ca kb_gap chép
    assert "no_evidence (bỏ no_evidence + max của ca đó): 1 {'LLMUnavailable': 1}" in said
    rows = pv.load_jsonl(out, pv.ProbRow)
    assert len(rows) == 28 + 27 * 2
    assert {r.scenario_id for r in rows if r.variant == "no_evidence"}.isdisjoint({"c07"})
    assert next(r.raw_prob for r in rows if r.scenario_id == "c00" and r.variant == "no_evidence") == 0.05


def test_cli_build_refuses_existing_output_and_input_overwrite(
    pv: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with_path, without_path = _write_inputs(pv, tmp_path)
    out = tmp_path / "probs.jsonl"
    assert pv.main(["build", str(with_path), str(without_path), str(out)]) == 0
    first = out.read_bytes()
    assert pv.main(["build", str(with_path), str(without_path), str(out)]) == 2
    assert out.read_bytes() == first
    before = with_path.read_bytes()
    assert pv.main(["build", str(with_path), str(without_path), str(with_path)]) == 2
    assert with_path.read_bytes() == before
    assert "LỖI" in capsys.readouterr().err


def test_cli_build_bad_input_exits_2_without_output(pv: ModuleType, tmp_path: Path) -> None:
    with_path, without_path = _write_inputs(pv, tmp_path)
    without_path.write_text("không phải json\n", encoding="utf-8")
    out = tmp_path / "probs.jsonl"
    assert pv.main(["build", str(with_path), str(without_path), str(out)]) == 2
    assert not out.exists()


def test_cli_compare_prints_both_scopes_and_writes_json(pv: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with_path, without_path = _write_inputs(pv, tmp_path)
    out = tmp_path / "probs.jsonl"
    assert pv.main(["build", str(with_path), str(without_path), str(out)]) == 0
    capsys.readouterr()
    js = tmp_path / "so-sanh.json"
    assert pv.main(["compare", str(with_path), str(out), "--json", str(js)]) == 0
    said = capsys.readouterr().out
    for v in ("with_evidence", "no_evidence", "max"):
        assert f"own      {v}" in said and f"common   {v}" in said
    data = json.loads(js.read_text(encoding="utf-8"))
    assert len(data) == 6 and {d["scope"] for d in data} == {"own", "common"}
    assert not any(re.search(r"best|win|choice", k) for d in data for k in d)


def test_cli_has_only_build_and_compare_and_no_variants_flag(pv: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        pv.main(["build", "--help"])
    with pytest.raises(SystemExit):
        pv.main(["compare", "--help"])
    helped = capsys.readouterr().out
    assert "--variants" not in helped
    with pytest.raises(SystemExit):
        pv.main(["fit", "x"])


# ---- phạm vi: không backend/config, không M8 gate, không .env ----------------------------------------------------------


def test_script_scope_static() -> None:
    src = (REPO / SCRIPT).read_text(encoding="utf-8")
    # không cần EVAL_MODE để nạp script / chạy build, compare: cấm import `app.eval` ở MỨC MODULE. `collect-no-evidence` (nối mốc G) nạp muộn,
    # TRONG hàm `_collect_run`, và tự từ chối khi thiếu EVAL_MODE (test_collect_no_evidence_script_refuses_without_eval_mode).
    assert not re.search(r"^(from|import)\s+app\.eval", src, re.MULTILINE)
    assert len(re.findall(r"^\s+from app\.eval", src, re.MULTILINE)) == len(re.findall(r"^        from app\.eval", src, re.MULTILINE))
    assert not re.search(r"""['"][^'"]*\.env['"]""", src)  # không mở .env
    assert "eval/scenarios" not in src and "kb/" not in src
    assert not re.search(r"\b(httpx|requests|urllib|socket)\b", src)  # không gọi mạng
    assert not re.search(r"self_report|sampling_k5|token_logprob|logprob", src.split('"""', 2)[2])  # ngoài docstring: không biến thể RQ2
