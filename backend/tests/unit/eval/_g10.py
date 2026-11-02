"""Dựng dữ liệu + gateway giả cho test G10 (thu `no_evidence`). Gateway = `LLMClient` THẬT + ScriptedLLM (tests.fakes.llm), prompt
`b14_risk_vote` (sampling_k5 = 5 phiếu/ca). Không mạng, không key thật."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.policy import BusinessHours
from app.risk.context import build_ctx
from app.settings import load_policy
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.scripted_llm import Reply, Step, Unavailable

NOW = datetime(2026, 10, 21, 3, 0, tzinfo=UTC)  # thứ Tư 10:00 giờ VN — trong giờ hành chính
CONFIG = Path(__file__).resolve().parents[4] / "config"
HOURS: BusinessHours = load_policy(CONFIG / "policy.json").business_hours
VOTES = [True, True, False, True, False]  # → 0,6


def votes(variables: Mapping[str, Any]) -> Step:
    return Reply({"needs_human": VOTES[int(variables["sample_idx"])], "factors": []})


def gateway() -> Gateway:
    return make_gateway({"b14_risk_vote": votes})


def factory(run_id: str, **_: Any) -> Any:
    """`--llm-factory tests.unit.eval._g10:factory` — gateway mới mỗi lần gọi (`fn(run_id[, max_usd=…])`, như `eval_gateway`)."""
    return gateway().client


def failing_factory(run_id: str, **_: Any) -> Any:
    """Mọi phiếu `LLMUnavailable` → mỗi ca một dòng `error` (hợp đồng WITHOUT.jsonl), lượt không dừng."""
    return make_gateway({"b14_risk_vote": lambda _v: Unavailable()}).client


def action(requested_for: str = "nv001", cert: str = "expired") -> Action:
    return Action(type="renew_vpn_cert", target="device:LAP-0342", requested_for=requested_for, scope="single_device",
                  privilege_level="standard_user", reversible=True, reversibility="full", data_sensitivity="low",
                  params={"device_id": "LAP-0342"},
                  facts={"device_registered": True, "device_owner_is_requester": True, "cert_status": cert})  # fmt: skip


def requester() -> RequesterContext:
    return RequesterContext(user_id="nv001", role="employee", department="finance", manager_id="ql007", employment_status="active",
                            tenure_days=400, is_privileged_account=False, captured_at=NOW)  # fmt: skip


def case(scenario_id: str, cert: str = "expired") -> dict[str, Any]:
    act = action(cert=cert)
    ctx = build_ctx({"intended_action": act, "requester_context": requester(), "ctx_flags": {}}, NOW, HOURS)
    return {"scenario_id": scenario_id, "action": act.model_dump(mode="json"), "ctx": ctx.model_dump(mode="json")}


def with_row(scenario_id: str, *, raw_prob: float = 0.3, kb_gap: bool = False, split: str = "test") -> dict[str, Any]:
    return {"scenario_id": scenario_id, "family": scenario_id.split("-")[0], "split": split, "gold_route": "HITL",
            "raw_prob": raw_prob, "kb_gap": kb_gap}  # fmt: skip
