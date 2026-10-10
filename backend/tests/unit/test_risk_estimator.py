"""B14 estimator LLM (phase6 5.1 P1–P9, bảng 5.6 es1–es10) + việc tự quyết đã duyệt (PLAN-6B mục 3: TQ-4, TQ-5; Q-6B-4 = A).

Kỳ vọng chép từ spec/PLAN, không suy từ code. Hai cách kiểm:
- **LlmPort giả** (`RecordingLlm`) ghi lại mọi lời gọi kèm `temperature`/`cache_policy` — `CallRecord` của ScriptedLLM không
  có hai trường này (5.6 es1).
- **Gateway thật** (`make_gateway`) + ScriptedLLM: render, whitelist, cache, retry, sửa schema chạy thật. Kịch bản k = 5 gắn
  phiếu theo `sample_idx` bằng kịch bản dạng HÀM (5.5: thứ tự `asyncio.gather` không cố định).
"""

import ast
import dataclasses
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.core.errors import LLMSchemaError, LLMUnavailable
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.risk_factors import FactorCode
from app.domain.ticket_state import ChunkRef
from app.llm.cache import cache_key
from app.llm.context import render
from app.llm.ports import CachePolicy, LLMMeta, Role, Sensitivity
from app.llm.schemas import RiskEstimateOut, RiskVoteOut
from app.risk.estimator import LlmRiskEstimator, RiskEstimate, estimator_vars
from app.risk.factors import FACTOR_LABELS
from app.risk.models import RiskContext
from pydantic import BaseModel
from tests.fakes.llm import make_gateway, repo_registry
from tests.fakes.scripted_llm import BadJSON, Reply, Script, Step, Unavailable
from tests.unit.test_llm_prompts import llm_call_sites, site_errors

REPO = Path(__file__).resolve().parents[3]
PROMPTS = REPO / "config" / "prompts"
RISK = REPO / "backend" / "app" / "risk"

NOW = datetime(2026, 10, 7, 3, 0, tzinfo=UTC)  # thứ Tư 10:00 giờ VN
CAPTURED = datetime(2026, 10, 7, 2, 59, tzinfo=UTC)

# P8 — đúng thứ tự, mã + nhãn
P8_FACTORS: list[tuple[str, str]] = [
    ("target_is_other", "tác động lên người/máy khác"),
    ("privileged_target", "tài khoản/quyền mức cao"),
    ("service_account", "tài khoản dịch vụ"),
    ("sensitive_data", "dữ liệu nhạy cảm"),
    ("cross_department", "tài nguyên phòng ban khác"),
    ("long_duration", "thời hạn dài"),
    ("irreversible", "khó hoàn tác"),
    ("outside_business_hours", "ngoài giờ hành chính"),
    ("new_employee", "nhân viên mới/thử việc"),
    ("account_status_abnormal", "tài khoản không ở trạng thái bình thường"),
    ("no_policy_evidence", "không có tài liệu quy định liên quan"),
    ("missing_facts", "thiếu dữ kiện"),
    ("routine_low_risk", "việc thường ngày, rủi ro thấp"),
]

# P2 — biến bị cấm trong prompt B14 (câu người dùng dưới mọi tên)
FORBIDDEN_VARS = {"redacted_request", "conversation", "slots", "text", "recent_messages", "raw_request"}
ESTIMATE_VARS = {"intended_action", "risk_context", "evidence"}
VOTE_VARS = ESTIMATE_VARS | {"sample_idx"}


# ---- fixture dữ liệu ---------------------------------------------------------------------------------------


def _requester() -> RequesterContext:
    return RequesterContext(
        user_id="nv001", role="employee", department="finance", manager_id="ql007", employment_status="active",
        tenure_days=400, is_privileged_account=False, captured_at=CAPTURED,
    )  # fmt: skip


def _ctx(*, within: bool = True, target_is_other: bool = False) -> RiskContext:
    return RiskContext(requester=_requester(), facts={"device_registered": True}, now=NOW,
                       within_business_hours=within, target_is_other=target_is_other)  # fmt: skip


def _vpn() -> Action:
    return Action(
        type="renew_vpn_cert", target="device:LAP-0342", requested_for="nv001", scope="single_device",
        privilege_level="standard_user", reversible=True, reversibility="full", data_sensitivity="low",
        params={"device_id": "LAP-0342"},
        facts={"device_registered": True, "device_owner_is_requester": True, "cert_status": "expired"},
    )  # fmt: skip


def _account() -> Action:
    return Action(
        type="reset_password", target="user:nv002", requested_for="nv002", scope="single_account",
        privilege_level="standard_user", reversible=True, reversibility="partial", data_sensitivity="medium",
        params={}, facts={"target_user_status": "active"},
    )  # fmt: skip


def _software() -> Action:
    return Action(
        type="install_software", target="device:LAP-0342", requested_for="nv001", scope="single_device",
        privilege_level="standard_user", reversible=True, reversibility="partial", data_sensitivity="low",
        params={"device_id": "LAP-0342", "software_name": "7-Zip"},
        facts={"in_catalog": True, "device_owner_is_requester": True},
    )  # fmt: skip


def _access() -> Action:
    return Action(
        type="grant_permission", target="folder:finance/Q3", requested_for="nv001", scope="single_account",
        privilege_level="standard_user", reversible=True, reversibility="full", data_sensitivity="medium",
        params={"permission_level": "read", "duration_days": 30}, facts={"resource_sensitivity": "medium"},
    )  # fmt: skip


def _chunk(i: int, score: float) -> ChunkRef:
    return ChunkRef(chunk_id=f"KB-VPN-004#{i}", doc_id="KB-VPN-004", version=1, seq=i, title=f"Tiêu đề {i}",
                    heading_path=f"Gia hạn > Bước {i}", score=score, excerpt=f"trích-đoạn-số-{i}")  # fmt: skip


def _block(c: ChunkRef) -> dict[str, Any]:
    """P4: ChunkRef → khối renderer (chunk_id → anchor_chunk_id, excerpt → text)."""
    return {"anchor_chunk_id": c.chunk_id, "title": c.title, "heading_path": c.heading_path, "text": c.excerpt,
            "score": c.score}  # fmt: skip


ESTIMATE_OK: dict[str, Any] = {"prob_needs_human": 0.42, "factors": ["target_is_other", "sensitive_data"],
                               "rationale": "ổn"}  # fmt: skip

# es4: phiếu theo sample_idx — needs_human [T, T, F, T, F] → p = 0,6
VOTES: dict[int, dict[str, Any]] = {
    0: {"needs_human": True, "factors": ["target_is_other", "sensitive_data"]},
    1: {"needs_human": True, "factors": ["sensitive_data", "long_duration"]},
    2: {"needs_human": False, "factors": ["routine_low_risk"]},
    3: {"needs_human": True, "factors": ["sensitive_data", "target_is_other", "irreversible"]},
    4: {"needs_human": False, "factors": ["routine_low_risk", "cross_department"]},
}
# Đếm trên MỌI phiếu ("hợp các lần", P6): sensitive_data 3; routine_low_risk 2, target_is_other 2; cross_department 1,
# irreversible 1, long_duration 1 → tần suất giảm, hoà theo tên mã, cắt 5.
VOTES_FACTORS = (FactorCode.SENSITIVE_DATA, FactorCode.ROUTINE_LOW_RISK, FactorCode.TARGET_IS_OTHER,
                 FactorCode.CROSS_DEPARTMENT, FactorCode.IRREVERSIBLE)  # fmt: skip


def _by_idx(replies: Mapping[int, Step]) -> Callable[[Mapping[str, Any]], Step]:
    """Kịch bản dạng hàm: bước phụ thuộc `variables["sample_idx"]` (5.5) — mọi lần thử của idx đó nhận cùng bước."""

    def script(variables: Mapping[str, Any]) -> Step:
        return replies[int(variables["sample_idx"])]

    return script


# ---- LlmPort giả ghi lại lời gọi (es1, es4) ---------------------------------------------------------------


@dataclass(frozen=True)
class PortCall:
    role: str
    prompt_id: str
    variables: dict[str, Any]
    schema: type[BaseModel]
    kwargs: dict[str, Any]


class RecordingLlm:
    """Thoả `LlmPort`; ghi (role, prompt_id, variables, schema, kwargs); trả `schema.model_validate(reply)` + `LLMMeta`."""

    def __init__(self, reply: Callable[[str, Mapping[str, Any]], dict[str, Any]], *, model: str = "strong-gia",
                 prompt_version: str = "9") -> None:  # fmt: skip
        self._reply = reply
        self._model = model
        self._prompt_version = prompt_version
        self.calls: list[PortCall] = []

    async def complete[T: BaseModel](
        self,
        role: Role,
        prompt_id: str,
        variables: Mapping[str, Any],
        schema: type[T],
        *,
        sensitivity: Sensitivity = "internal",
        cache_policy: CachePolicy = "default",
        n: int = 1,
        temperature: float | None = None,
        kb_version: str | None = None,
    ) -> tuple[T, LLMMeta]:
        self.calls.append(PortCall(role, prompt_id, dict(variables), schema, {
            "sensitivity": sensitivity, "cache_policy": cache_policy, "n": n, "temperature": temperature,
            "kb_version": kb_version,
        }))  # fmt: skip
        meta = LLMMeta(
            span_id=f"span-{len(self.calls)}", provider="gia", model=self._model, model_version=None,
            prompt_id=prompt_id, prompt_version=self._prompt_version, prompt_hash="h" * 64, tokens_in=1, tokens_out=1,
            cost_usd=0.0, latency_ms=1, cache_hit=False, json_valid_first_try=True, used_fallback=False,
        )  # fmt: skip
        return schema.model_validate(self._reply(prompt_id, variables)), meta


def _estimate_reply(prompt_id: str, variables: Mapping[str, Any]) -> dict[str, Any]:
    return dict(ESTIMATE_OK)


def _vote_reply(prompt_id: str, variables: Mapping[str, Any]) -> dict[str, Any]:
    return dict(VOTES[int(variables["sample_idx"])])


# ---- es1: tự nêu ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("eval_mode", "policy"), [(False, "bypass"), (True, "default")])
async def test_es1_self_report_call_params_via_recording_port(eval_mode: bool, policy: str) -> None:
    """es1 (P5): 1 lời gọi b14_risk_estimate, strong, temperature=0.0, cache_policy theo eval_mode; RiskEstimate từ LLMMeta."""
    port = RecordingLlm(_estimate_reply)
    action, ctx, evidence = _vpn(), _ctx(), [_chunk(0, 0.8)]
    est = await LlmRiskEstimator(port, p_method="self_report", eval_mode=eval_mode).estimate(action, ctx, evidence)
    assert len(port.calls) == 1
    (call,) = port.calls
    assert (call.role, call.prompt_id, call.schema) == ("strong", "b14_risk_estimate", RiskEstimateOut)
    assert call.kwargs["temperature"] == 0.0 and call.kwargs["temperature"] is not None
    assert call.kwargs["cache_policy"] == policy
    assert call.variables == estimator_vars(action, ctx, evidence)
    assert est == RiskEstimate(
        raw_prob=0.42, p_method="self_report", factors=(FactorCode.TARGET_IS_OTHER, FactorCode.SENSITIVE_DATA),
        prompt_id="b14_risk_estimate", prompt_version="9", model="strong-gia",
    )  # fmt: skip


@pytest.mark.asyncio
async def test_es1_gateway_runtime_never_caches() -> None:
    """es1 (P5, Q-6-6): qua gateway thật, eval_mode=False → cache_policy bypass → 0 dòng cache, mỗi lần đều tới provider."""
    gw = make_gateway({"b14_risk_estimate": [Reply(ESTIMATE_OK), Reply(ESTIMATE_OK)]})
    estimator = LlmRiskEstimator(gw.client, p_method="self_report", eval_mode=False)
    for _ in range(2):
        est = await estimator.estimate(_vpn(), _ctx(), [_chunk(0, 0.8)])
        assert est.raw_prob == 0.42
    assert gw.store.cache == {}
    assert len(gw.llm.calls) == 2
    (first, _second) = gw.llm.calls
    assert (est.prompt_id, est.prompt_version, est.model) == ("b14_risk_estimate", "1", first.model)


@pytest.mark.asyncio
async def test_es1_gateway_eval_mode_second_call_hits_cache() -> None:
    """es1: eval_mode=True + cache_mode="eval" → lần gọi 2 không tới provider."""
    gw = make_gateway({"b14_risk_estimate": [Reply(ESTIMATE_OK), Reply(ESTIMATE_OK)]}, eval_mode=True,
                      cache_mode="eval")  # fmt: skip
    estimator = LlmRiskEstimator(gw.client, p_method="self_report", eval_mode=True)
    a = await estimator.estimate(_vpn(), _ctx(), [_chunk(0, 0.8)])
    b = await estimator.estimate(_vpn(), _ctx(), [_chunk(0, 0.8)])
    assert len(gw.llm.calls) == 1
    assert a.raw_prob == b.raw_prob == 0.42
    assert len(gw.store.cache) == 1


# ---- es2: biến prompt (hàm thuần) -------------------------------------------------------------------------


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {str(k) for k in value} | {k for v in value.values() for k in _all_keys(v)}
    if isinstance(value, list | tuple):
        return {k for v in value for k in _all_keys(v)}
    return set()


def test_es2_keys_equal_allowed_vars_and_intended_action_full() -> None:
    """es2 (P2, P3): khoá = allowed_vars của b14_risk_estimate; intended_action = Action.model_dump(mode="json")."""
    action = _access()
    variables = estimator_vars(action, _ctx(), [])
    assert set(variables) == set(repo_registry().get("b14_risk_estimate").spec.allowed_vars) == ESTIMATE_VARS
    ia = variables["intended_action"]
    assert {"type", "facts", "params"} <= set(ia)
    assert ia == action.model_dump(mode="json")


def test_es2_risk_context_drops_time_and_identity() -> None:
    """es2 (P3): risk_context KHÔNG có now, captured_at, user_id, manager_id (kiểm trên dict, ở mọi tầng lồng)."""
    rc = estimator_vars(_vpn(), _ctx(within=False, target_is_other=True), [])["risk_context"]
    assert not _all_keys(rc) & {"now", "captured_at", "user_id", "manager_id"}
    # P3 "chỉ {requester: {…5 trường}, within_business_hours, target_is_other}"
    assert rc == {
        "requester": {"role": "employee", "department": "finance", "employment_status": "active", "tenure_days": 400,
                      "is_privileged_account": False},
        "within_business_hours": False,
        "target_is_other": True,
    }  # fmt: skip


def test_es2_evidence_top3_by_score_mapped_to_renderer_blocks() -> None:
    """es2 (P4, TQ-7): 5 chunk → đúng 3 điểm cao nhất (sắp điểm giảm), mỗi khối đủ 5 khoá P4 với ánh xạ chunk_id/excerpt."""
    chunks = [_chunk(0, 0.30), _chunk(1, 0.90), _chunk(2, 0.50), _chunk(3, 0.70), _chunk(4, 0.10)]
    evidence = estimator_vars(_vpn(), _ctx(), chunks)["evidence"]
    assert len(evidence) == 3
    for block in evidence:
        assert set(block) == {"anchor_chunk_id", "title", "heading_path", "text", "score"}
    assert {b["anchor_chunk_id"] for b in evidence} == {"KB-VPN-004#1", "KB-VPN-004#3", "KB-VPN-004#2"}
    assert list(evidence) == [_block(chunks[1]), _block(chunks[3]), _block(chunks[2])]


def test_es2_fewer_than_three_chunks_kept() -> None:
    """es2 (P4): "tối đa 3" — 2 chunk → 2 khối."""
    chunks = [_chunk(0, 0.4), _chunk(1, 0.6)]
    evidence = estimator_vars(_vpn(), _ctx(), chunks)["evidence"]
    assert sorted(b["anchor_chunk_id"] for b in evidence) == ["KB-VPN-004#0", "KB-VPN-004#1"]


def test_es2_renders_and_empty_evidence_is_khong_co() -> None:
    """es2 (P4): biến render được qua renderer thật; trích đoạn rỗng → "(không có)"."""
    registry = repo_registry()
    chunks = [_chunk(0, 0.30), _chunk(1, 0.90), _chunk(2, 0.50), _chunk(3, 0.70), _chunk(4, 0.10)]
    full = render(registry.get("b14_risk_estimate"), estimator_vars(_vpn(), _ctx(), chunks), budget_in=6000)
    user = full.messages[1]["content"]
    assert all(f"trích-đoạn-số-{i}" in user for i in (1, 2, 3))
    assert "trích-đoạn-số-0" not in user and "trích-đoạn-số-4" not in user
    empty = estimator_vars(_vpn(), _ctx(), [])
    for prompt_id, variables in (("b14_risk_estimate", empty), ("b14_risk_vote", {**empty, "sample_idx": 0})):
        rendered = render(registry.get(prompt_id), variables, budget_in=6000)
        assert "(không có)" in rendered.messages[1]["content"]


# ---- es3: 4 intent ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("make_action", [_vpn, _account, _software, _access], ids=["vpn", "account", "software", "access"])
async def test_es3_four_intents_render_one_call_each(make_action: Callable[[], Action]) -> None:
    """es3 (5.5): Action vpn/account/software/access dựng trực tiếp → render được qua gateway thật, đúng 1 lời gọi."""
    gw = make_gateway({"b14_risk_estimate": [Reply(ESTIMATE_OK)]})
    est = await LlmRiskEstimator(gw.client, p_method="self_report", eval_mode=False).estimate(
        make_action(), _ctx(), [_chunk(0, 0.8)])  # fmt: skip
    assert len(gw.llm.calls) == 1 and gw.llm.calls[0].prompt_id == "b14_risk_estimate"
    assert est.raw_prob == 0.42


# ---- es4: k = 5 -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("eval_mode", "policy"), [(False, "bypass"), (True, "default")])
async def test_es4_k5_call_params_via_recording_port(eval_mode: bool, policy: str) -> None:
    """es4 (P6): 5 lời gọi b14_risk_vote, RiskVoteOut, temperature=0.7, sample_idx 0…4, cache_policy như P5."""
    port = RecordingLlm(_vote_reply)
    action, ctx, evidence = _software(), _ctx(), [_chunk(0, 0.8)]
    est = await LlmRiskEstimator(port, p_method="sampling_k5", eval_mode=eval_mode).estimate(action, ctx, evidence)
    assert len(port.calls) == 5
    base = estimator_vars(action, ctx, evidence)
    assert sorted(c.variables["sample_idx"] for c in port.calls) == [0, 1, 2, 3, 4]
    for c in port.calls:
        assert (c.role, c.prompt_id, c.schema) == ("strong", "b14_risk_vote", RiskVoteOut)
        assert c.kwargs["temperature"] == 0.7
        assert c.kwargs["cache_policy"] == policy
        assert c.variables == {**base, "sample_idx": c.variables["sample_idx"]}
    assert est.p_method == "sampling_k5"
    assert est.raw_prob == pytest.approx(0.6, abs=1e-12)
    assert est.factors == VOTES_FACTORS
    assert (est.prompt_id, est.prompt_version, est.model) == ("b14_risk_vote", "9", "strong-gia")


@pytest.mark.asyncio
async def test_es4_k5_gateway_five_distinct_renders_keys_p06_factor_order() -> None:
    """es4 (P6): qua gateway thật — 5 bản render khác nhau → 5 `cache_key` khác nhau; [T,T,F,T,F] → 0,6; factors theo P6."""
    replies: dict[int, Step] = {i: Reply(v) for i, v in VOTES.items()}
    scripts: dict[str, Script] = {"b14_risk_vote": _by_idx(replies)}
    gw = make_gateway(scripts)
    est = await LlmRiskEstimator(gw.client, p_method="sampling_k5", eval_mode=False).estimate(
        _vpn(), _ctx(), [_chunk(0, 0.8), _chunk(1, 0.6)])  # fmt: skip
    calls = gw.llm.calls_for("b14_risk_vote")
    assert len(calls) == 5 and len(gw.llm.calls) == 5
    assert sorted(int(c.variables["sample_idx"]) for c in calls) == [0, 1, 2, 3, 4]
    renders = [c.rendered_messages for c in calls]
    assert len({repr(m) for m in renders}) == 5
    keys = {
        cache_key(provider="scripted", model=c.model, model_version=None, prompt_id="b14_risk_vote", prompt_version="1",
                  messages=c.rendered_messages, json_schema=RiskVoteOut.model_json_schema(), temperature=0.7, n=1,
                  kb_version=None, mode="eval")
        for c in calls
    }  # fmt: skip
    assert len(keys) == 5
    assert est.raw_prob == pytest.approx(0.6, abs=1e-12)
    assert est.p_method == "sampling_k5"
    assert est.factors == VOTES_FACTORS
    assert (est.prompt_id, est.prompt_version) == ("b14_risk_vote", "1")


# ---- es5: k = 5, một lời gọi lỗi --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_es5_k5_one_unavailable_call_fails_whole_estimate() -> None:
    """es5 (P6): lời gọi sample_idx 2 LLMUnavailable (mọi lần thử) → estimate ném LLMUnavailable, không trả p."""
    replies: dict[int, Step] = {i: Reply(v) for i, v in VOTES.items()}
    replies[2] = Unavailable()
    gw = make_gateway({"b14_risk_vote": _by_idx(replies)})
    estimator = LlmRiskEstimator(gw.client, p_method="sampling_k5", eval_mode=False)
    with pytest.raises(LLMUnavailable):
        await estimator.estimate(_vpn(), _ctx(), [_chunk(0, 0.8)])
    assert 2 in {int(c.variables["sample_idx"]) for c in gw.llm.calls}


# ---- es6: schema xấu --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    Reply({"prob_needs_human": 1.2, "factors": [], "rationale": "x"}),
    BadJSON('{"prob_needs_human": NaN, "factors": [], "rationale": "x"}'),
    Reply({"prob_needs_human": 0.3, "factors": ["ma_khong_ton_tai"], "rationale": "x"}),
], ids=["1.2", "NaN", "unknown_factor"])  # fmt: skip
async def test_es6_bad_schema_after_repair_is_schema_error(bad: Step) -> None:
    """es6 (P7, 5.5): 1,2 / NaN / mã yếu tố lạ — sai cả lần đầu lẫn lần sửa của gateway → LLMSchemaError."""
    gw = make_gateway({"b14_risk_estimate": lambda _v: bad})
    with pytest.raises(LLMSchemaError):
        await LlmRiskEstimator(gw.client, p_method="self_report", eval_mode=False).estimate(_vpn(), _ctx(), [])


@pytest.mark.asyncio
async def test_es6_vote_unknown_factor_is_schema_error() -> None:
    """es6 (P7, 5.5 "mã yếu tố lạ" cho b14_risk_vote): mọi phiếu có mã lạ → LLMSchemaError."""
    gw = make_gateway({"b14_risk_vote": lambda _v: Reply({"needs_human": True, "factors": ["ma_khong_ton_tai"]})})
    with pytest.raises(LLMSchemaError):
        await LlmRiskEstimator(gw.client, p_method="sampling_k5", eval_mode=False).estimate(_vpn(), _ctx(), [])


# ---- es7: whitelist trên file thật ------------------------------------------------------------------------


@pytest.mark.parametrize(("prompt_id", "expected_vars"), [("b14_risk_estimate", ESTIMATE_VARS),
                                                         ("b14_risk_vote", VOTE_VARS)])  # fmt: skip
def test_es7_real_prompt_whitelist_cache_role(prompt_id: str, expected_vars: set[str]) -> None:
    """es7 (P2, P9): file prompt thật — allowed_vars ∩ tập cấm = ∅; cache: default; role: strong."""
    data = yaml.safe_load((PROMPTS / f"{prompt_id}.yaml").read_text(encoding="utf-8"))
    allowed = set(data["allowed_vars"])
    assert not allowed & FORBIDDEN_VARS, sorted(allowed & FORBIDDEN_VARS)
    assert allowed == expected_vars
    assert data["cache"] == "default"
    assert data["role"] == "strong"
    assert data["id"] == prompt_id and str(data["version"]) == "1"


# ---- es8: AST ---------------------------------------------------------------------------------------------

AST_FILES = ("estimator.py", "strategy.py", "factors.py")
AST_MARKERS = {"estimator.py": "LlmRiskEstimator", "strategy.py": "decide", "factors.py": "FACTOR_LABELS"}
USER_REFS = {"state", "redacted_request", "conversation", "slots"}
FORBIDDEN_IMPORTS = ("app.graph", "app.api", "app.guard")


def _names(tree: ast.AST) -> set[str]:
    """Khuôn `test_policy_engine_signature.py:82-89`: Name.id + Attribute.attr + hằng chuỗi — so khớp NGUYÊN CHỮ."""
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        str(n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


def _imports(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module is not None:
            mods.add(n.module)
            mods |= {f"{n.module}.{a.name}" for a in n.names}
    return mods


def _bad_imports(mods: set[str]) -> set[str]:
    return {m for m in mods if any(m == p or m.startswith(p + ".") for p in FORBIDDEN_IMPORTS)}


@pytest.mark.parametrize("name", AST_FILES)
def test_es8_risk_modules_never_reference_user_text_or_graph(name: str) -> None:
    """es8: risk/{estimator,strategy,factors}.py không tham chiếu state/redacted_request/conversation/slots; không import
    app.graph, app.api, app.guard."""
    tree = ast.parse((RISK / name).read_text(encoding="utf-8"))
    names, mods = _names(tree), _imports(tree)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)}
    defined |= {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign | ast.AnnAssign)
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}  # fmt: skip
    has_marker, scanned = AST_MARKERS[name] in defined, len(names) > 0 and len(mods) > 0
    assert has_marker, "không thấy định nghĩa mong đợi — bộ quét hỏng (chống xanh giả)"
    assert scanned, "không quét được tên/import nào — bộ quét hỏng (chống xanh giả)"
    leaked, bad_mods = sorted(names & USER_REFS), sorted(_bad_imports(mods))
    assert leaked == []
    assert bad_mods == []


def test_es8_scanner_catches_planted_references() -> None:
    """es8 đối chứng: bộ quét bắt được state["slots"], .redacted_request, import app.graph / from app import guard."""
    src = (
        "import app.api.routes\nfrom app.graph.nodes import b12_assess\nfrom app import guard\n"
        "def f(x):\n    return x.redacted_request, conversation, {'slots': 1}\n"
        "def g(state):\n    return state['k']\n"
    )
    tree = ast.parse(src)
    assert USER_REFS <= _names(tree)
    assert _bad_imports(_imports(tree)) == {"app.api.routes", "app.graph.nodes", "app.graph.nodes.b12_assess",
                                            "app.guard"}  # fmt: skip
    assert "state" not in _names(ast.parse("x = 'trạng thái state hỏng'\ny = states"))  # so nguyên chữ, không so chuỗi con


# ---- es9: rationale không thoát ---------------------------------------------------------------------------

CANARY = "CANARY-b14-rationale-9f2c"


def test_es9_risk_estimate_has_no_rationale_field() -> None:
    """es9 (P7, Q-6-5): RiskEstimate không có trường nào chứa "rationale"; trường đúng P1."""
    names = [f.name for f in dataclasses.fields(RiskEstimate)]
    assert not [n for n in names if "rationale" in n]
    assert set(names) == {"raw_prob", "p_method", "factors", "prompt_id", "prompt_version", "model"}


@pytest.mark.asyncio
async def test_es9_rationale_canary_not_in_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    """es9: canary trong `rationale` của phản hồi không có trong repr(RiskEstimate) và log bắt được (DEBUG)."""
    caplog.set_level(logging.DEBUG)
    reply = {**ESTIMATE_OK, "rationale": f"lý do {CANARY}"}
    gw = make_gateway({"b14_risk_estimate": [Reply(reply)]})
    est = await LlmRiskEstimator(gw.client, p_method="self_report", eval_mode=False).estimate(_vpn(), _ctx(), [])
    assert est.raw_prob == 0.42
    assert CANARY not in repr(est) and CANARY not in str(est)
    assert CANARY not in caplog.text


# ---- es10: lời gọi LLM tĩnh trong risk/ -------------------------------------------------------------------


def test_es10_risk_package_llm_call_sites_match_registry() -> None:
    """es10: llm_call_sites trên backend/app/risk/*.py — đúng 2 lời gọi (b14_risk_estimate, b14_risk_vote), role + schema
    khớp registry; lỗi "dict literal" bỏ qua (biến kiểm bằng es2)."""
    files = sorted(RISK.glob("*.py"))
    assert "estimator.py" in {f.name for f in files} and len(files) >= 3  # tập quét không rỗng
    sites = [s for f in files for s in llm_call_sites(f.read_text(encoding="utf-8"), f.name)]
    assert sorted(str(s.prompt_id) for s in sites) == ["b14_risk_estimate", "b14_risk_vote"]
    registry = repo_registry()
    errors = [e for s in sites for e in site_errors(s, registry) if "dict literal" not in e]
    assert errors == []


# ---- test_tq: hợp đồng tự quyết đã duyệt (PLAN-6B mục 3, Q-6B-4 = A) ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("steps", "expected"), [
    ({1: BadJSON("không phải JSON"), 3: Unavailable()}, LLMSchemaError),
    ({1: Unavailable(), 3: BadJSON("không phải JSON")}, LLMUnavailable),
], ids=["idx1_schema_idx3_unavailable", "idx1_unavailable_idx3_schema"])  # fmt: skip
async def test_tq4_k5_two_failures_raise_lowest_sample_idx(steps: Mapping[int, Step],
                                                           expected: type[Exception]) -> None:  # fmt: skip
    """TQ-4: ≥ 2 lời gọi k = 5 lỗi khác loại → ném lỗi của sample_idx nhỏ nhất (chờ đủ 5, lỗi tất định)."""
    replies: dict[int, Step] = {i: Reply(v) for i, v in VOTES.items()}
    replies.update(steps)
    gw = make_gateway({"b14_risk_vote": _by_idx(replies)})
    with pytest.raises(expected):
        await LlmRiskEstimator(gw.client, p_method="sampling_k5", eval_mode=False).estimate(_vpn(), _ctx(), [])
    assert {int(c.variables["sample_idx"]) for c in gw.llm.calls} == {0, 1, 2, 3, 4}  # cả 5 đều chạy


@pytest.mark.asyncio
async def test_tq5_duplicate_code_in_one_vote_counts_once() -> None:
    """TQ-5: mã lặp trong MỘT phiếu chỉ đếm 1 lần cho phiếu đó. long_duration ×3 trong phiếu 0 (= 1 phiếu) < irreversible
    ở 2 phiếu → irreversible đứng trước; kết quả không trùng mã."""
    votes: dict[int, dict[str, Any]] = {
        0: {"needs_human": True, "factors": ["long_duration", "long_duration", "long_duration"]},
        1: {"needs_human": True, "factors": ["irreversible"]},
        2: {"needs_human": True, "factors": ["irreversible"]},
        3: {"needs_human": False, "factors": []},
        4: {"needs_human": False, "factors": []},
    }
    port = RecordingLlm(lambda _p, v: dict(votes[int(v["sample_idx"])]))
    est = await LlmRiskEstimator(port, p_method="sampling_k5", eval_mode=False).estimate(_vpn(), _ctx(), [])
    assert est.raw_prob == pytest.approx(0.6, abs=1e-12)
    assert est.factors == (FactorCode.IRREVERSIBLE, FactorCode.LONG_DURATION)


@pytest.mark.asyncio
async def test_tq5_self_report_keeps_llm_factor_order() -> None:
    """TQ-5 (phần self_report): giữ thứ tự LLM trả (không sắp lại theo tên)."""
    reply = {"prob_needs_human": 0.2, "factors": ["routine_low_risk", "cross_department", "irreversible"],
             "rationale": "x"}  # fmt: skip
    port = RecordingLlm(lambda _p, _v: dict(reply))
    est = await LlmRiskEstimator(port, p_method="self_report", eval_mode=False).estimate(_vpn(), _ctx(), [])
    assert est.factors == (FactorCode.ROUTINE_LOW_RISK, FactorCode.CROSS_DEPARTMENT, FactorCode.IRREVERSIBLE)


@pytest.mark.parametrize("prompt_id", ["b14_risk_estimate", "b14_risk_vote"])
def test_tq_all_13_factor_codes_listed_in_prompt_system(prompt_id: str) -> None:
    """TQ (Q-6B-4): 13 mã FactorCode đều xuất hiện trong `system` của cả 2 prompt thật."""
    system = yaml.safe_load((PROMPTS / f"{prompt_id}.yaml").read_text(encoding="utf-8"))["system"]
    assert len(FactorCode) == 13
    missing = [c.value for c in FactorCode if c.value not in system]
    assert missing == []


def test_tq_factor_code_order_and_labels_cover_13() -> None:
    """TQ (Q-6B-4, P8, TQ-10): FactorCode đúng 13 mã theo thứ tự P8; set(FACTOR_LABELS) == set(FactorCode); 13 nhãn khác rỗng."""
    assert [c.value for c in FactorCode] == [code for code, _ in P8_FACTORS]
    assert all(FactorCode[code.upper()].value == code for code, _ in P8_FACTORS)
    assert set(FACTOR_LABELS) == set(FactorCode)
    assert len(FACTOR_LABELS) == 13
    assert all(isinstance(v, str) and v.strip() for v in FACTOR_LABELS.values())


def test_tq_factor_labels_match_p8_text() -> None:
    """P8: nhãn tiếng Việt chép đúng chữ (st17 dùng nhãn này trong `reason`)."""
    assert {c.value: FACTOR_LABELS[c] for c in FactorCode} == dict(P8_FACTORS)

