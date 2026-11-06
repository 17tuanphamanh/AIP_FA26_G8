"""`GET /api/tickets/{id}/trace` — "Nhật ký quyết định" chỉ đọc (api/trace.py). Không DB, không stack: nguồn dữ liệu là bản giả
gán vào `app.state.trace` (SQL thật: `SqlTraceSource`).

- Quyền: nhân viên 403 (+ `permission_denied`, không đọc dữ liệu); L1, L2, manager 200; không có → 404; L1/L2 bị `can_read_ticket`
  từ chối → CÙNG 404 + `permission_denied`; manager (`audit:read:all`) không qua `can_read_ticket`.
- Danh sách trắng: chuỗi canary cài vào câu người dùng (`detail.query`, `span`), prompt, ghi chú người duyệt, `reason`, tham số hành
  động, giá trị fact, traceback → KHÔNG xuất hiện trong thân trả về.
- Làm tròn 2 số; `decided_by`; trường thiếu → bỏ qua; ticket cha kèm con; OpenAPI có `TicketTrace`.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from app.api import trace as api
from app.api.matched_rules import RuleRef
from app.api.trace import TicketHead, TraceData, build_trace
from app.core.clock import FakeClock
from tests.fakes.auth import EPOCH
from tests.unit.auth_helpers import AuthEnv, auth_env
from tests.unit.test_auth_route_scan import route_auth

# Ghép lúc chạy — viết liền thì gitleaks có thể coi là khoá thật.
_CANARY_PARTS = ("CANARY", "trace", "5b1e")
CANARY = "-".join(_CANARY_PARTS)
USER_TEXT = f"Tôi quên mật khẩu VPN, mật khẩu cũ là {CANARY}"
URL = "/api/tickets/{}/trace"
RULES = {"R18": RuleRef("approval_required", "Gia hạn chứng chỉ VPN ngoài giờ cần duyệt")}


def _at(minutes: int) -> Any:
    return EPOCH + timedelta(minutes=minutes)


def _row(i: int, step: str, event: str, **cols: Any) -> dict[str, Any]:
    return {"log_id": i, "created_at": _at(i), "step": step, "event": event, "detail": {}, **cols}


def vpn_audit() -> list[dict[str, Any]]:
    """Một ticket VPN đi đủ B1 → B20 qua duyệt; mỗi dòng có chữ người dùng / prompt / tham số cài canary."""
    return [
        _row(1, "B1", "identity_established", detail={"note": CANARY}),
        _row(2, "B2", "screened", detail={"screening": {
            "layer_decided": "llm", "p_mal": 0.03456, "clf_mode": "shadow", "ml_error": None, "llm_is_attack": False,
            "llm_category": "none", "llm_role": "fast", "llm_model": "fast-model", "pattern_id": CANARY,
        }}),
        _row(3, "B3", "intent_classified", intent="vpn", confidence=0.95, detail={
            "layer": "llm", "intent": "vpn", "confidence": 0.951, "is_multi": False,
            "model_probs": {"vpn": 0.9712, "account": 0.0213, USER_TEXT: 0.5}, "model_version": "intent-clf@1",
            "prompt": f"b03_classify@v2 {CANARY}", "span": USER_TEXT, "llm_error": None,
        }),
        _row(4, "B6", "diagnosed", detail={
            "tools_called": ["check_vpn_cert_expiry"], "facts": {"cert_expired": CANARY, "device_registered": True,
                                                                 USER_TEXT: 1},
            "tool_errors": [CANARY],
        }),
        _row(5, "B8", "retrieved", detail={"query": USER_TEXT, "doc_ids": ["KB-VPN-001"], "top_score": 0.81}),
        _row(6, "B10", "needs_action", detail={"need_type": "action", "cited": [], "prompt": CANARY}),
        _row(7, "B11", "action_built", intended_action={
            "type": "renew_vpn_cert", "params": {"user_id": "nv001", "password": CANARY},
        }, detail={"slots": {"device_id": CANARY}}),
        _row(8, "B13/B14", "risk_decided", decided_by="rule", policy_decision="approval_required", risk_level="medium",
             matched_rule_id="R18", reason=f"Luật R18 {CANARY}", raw_prob=None, calibrated_prob=None,
             detail={"route": "HITL", "reason": CANARY, "all_matched": ["R18"]}),
        _row(9, "B15", "queued", approver_id="l1_01", detail={"choice_reason": "normal", "rejected_candidates": [CANARY]}),
        _row(10, "B16", "approved", approval_result="approved", note=CANARY, detail={"note": CANARY, "reason_code": None}),
        _row(11, "B18", "executed_ok", detail={
            "success": True, "steps_done": ["renew_vpn_cert"], "failed_step": None, "rollback_status": "none_needed",
            "write_calls": 1, "matched_rule_id": "R18", "params": {"password": CANARY},
        }),
        _row(12, "B20", "ticket_closed", exit_code=None, final_state="S_RESOLVED",
             detail={"resolution_path": "approved", "traceback": CANARY}),
    ]


APPROVALS = [{
    "approval_id": 1, "approver_id": "l1_01", "decided_by": "l1_01", "status": "approved", "decided_at": _at(10),
    "created_at": _at(9), "note": CANARY,
}]  # fmt: skip


def vpn_data(ticket_id: str = "T-1", requester: str = "nv001") -> TraceData:
    return TraceData(
        ticket=TicketHead(ticket_id, requester, None, False), audit=vpn_audit(), approvals=APPROVALS,
        names={"l1_01": "Lê Thu Hà"},
    )  # fmt: skip


class FakeTrace:
    def __init__(self, *items: TraceData) -> None:
        self.items = {d.ticket.ticket_id: d for d in items}
        self.loaded: list[str] = []

    async def head(self, ticket_id: str) -> TicketHead | None:
        d = self.items.get(ticket_id)
        return d.ticket if d is not None else None

    async def load(self, ticket: TicketHead) -> TraceData:
        self.loaded.append(ticket.ticket_id)
        return self.items[ticket.ticket_id]


@pytest.fixture(autouse=True)
def _rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "rule_index", lambda: dict(RULES))


@pytest.fixture
def source() -> FakeTrace:
    parent = TraceData(
        ticket=TicketHead("P-1", "nv001", None, True),
        audit=[_row(1, "B5", "split_into_2_children", detail={"is_multi": True, "children": 2, "intent": None})],
        children=[{"ticket_id": "P-1-1", "intent": "vpn", "exit_code": None},
                  {"ticket_id": "P-1-2", "intent": "account", "exit_code": "E1"}],
    )  # fmt: skip
    child = TraceData(ticket=TicketHead("P-1-1", "nv001", "P-1", False), audit=[_row(1, "B6", "diagnosed")])
    return FakeTrace(vpn_data(), parent, child)


@pytest.fixture
def env(source: FakeTrace) -> Iterator[AuthEnv]:
    with auth_env(clock=FakeClock(EPOCH)) as e:
        e.app.state.trace = source
        yield e


def _get(env: AuthEnv, ticket_id: str, token: str) -> Any:
    return env.client.get(URL.format(ticket_id), headers=env.bearer(token))


# ---- quyền ----------------------------------------------------------------------------------------


def test_employee_is_forbidden_even_for_own_ticket(env: AuthEnv, source: FakeTrace) -> None:
    r = _get(env, "T-1", env.token("an.nv"))  # an.nv = nv001, chủ ticket T-1
    assert r.status_code == 403 and r.json() == {"detail": "forbidden"}
    assert source.loaded == []
    denied = env.sink.of("permission_denied")
    assert len(denied) == 1 and denied[0].detail == {"perm": "ticket:read:any"}


def test_no_token_is_401(env: AuthEnv) -> None:
    assert env.client.get(URL.format("T-1")).status_code == 401


@pytest.mark.parametrize("username", ["ha.lt", "long.nh"])  # l1, l2
def test_l1_l2_read_trace(env: AuthEnv, username: str) -> None:
    r = _get(env, "T-1", env.token(username))
    assert r.status_code == 200
    assert r.json()["ticket_id"] == "T-1" and len(r.json()["steps"]) == 12


def test_manager_reads_trace(env: AuthEnv) -> None:
    r = _get(env, "T-1", env.manager_token())
    assert r.status_code == 200 and r.json()["ticket_id"] == "T-1"


def test_unknown_ticket_is_404(env: AuthEnv, source: FakeTrace) -> None:
    for token in (env.token("ha.lt"), env.manager_token()):
        r = _get(env, "T-404", token)
        assert r.status_code == 404 and r.json() == {"detail": "not_found"}
    assert source.loaded == [] and env.sink.of("permission_denied") == []  # id giả: không ghi gì


def test_l1_denied_by_can_read_ticket_gets_same_404(
    env: AuthEnv, source: FakeTrace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ma trận hiện tại cho L1/L2 `ticket:read:any` (luôn đọc được) — chốt rằng route VẪN hỏi `can_read_ticket`."""
    seen: list[str] = []

    def no(p: Any, t: Any) -> bool:
        seen.append(t.ticket_id)
        return False

    monkeypatch.setattr(api, "can_read_ticket", no)
    missing = _get(env, "T-404", env.token("ha.lt"))
    r = _get(env, "T-1", env.token("ha.lt"))
    assert r.status_code == 404 and r.json() == missing.json() == {"detail": "not_found"}
    assert seen == ["T-1"] and source.loaded == []
    denied = env.sink.of("permission_denied")
    assert len(denied) == 1 and denied[0].detail == {"perm": "ticket:read:any", "ticket_id": "T-1"}
    # manager (`audit:read:all`) đọc mọi ticket — không qua `can_read_ticket`
    assert _get(env, "T-1", env.manager_token()).status_code == 200 and seen == ["T-1"]


def test_marker_and_get_only(env: AuthEnv) -> None:
    found = [c for c in route_auth(env.app) if c.path == "/api/tickets/{ticket_id}/trace"]
    assert [(c.methods, c.requirements) for c in found] == [(frozenset({"GET"}), (("ticket:read:any", None, False),))]
    r = env.client.post(URL.format("T-1"), headers=env.bearer(env.token("ha.lt")))
    assert r.status_code == 405


def test_missing_source_is_503(env: AuthEnv) -> None:
    env.app.state.trace = None
    assert _get(env, "T-1", env.token("ha.lt")).status_code == 503


# ---- danh sách trắng ------------------------------------------------------------------------------


def test_canary_never_leaves(env: AuthEnv) -> None:
    for token in (env.token("ha.lt"), env.token("long.nh"), env.manager_token()):
        r = _get(env, "T-1", token)
        assert r.status_code == 200
        assert CANARY not in r.text and "CANARY" not in r.text
        assert "mật khẩu" not in r.text and "password" not in r.text and "params" not in r.text


def test_whitelisted_fields_per_step(env: AuthEnv) -> None:
    steps = {s["step"]: s for s in _get(env, "T-1", env.token("ha.lt")).json()["steps"]}
    assert [s for s in steps] == ["B1", "B2", "B3", "B6", "B8", "B10", "B11", "B13/B14", "B15", "B16", "B18", "B20"]
    assert steps["B1"] | {"at": None} == {"step": "B1", "event": "identity_established", "at": None, **dict.fromkeys(
        ("screen", "classify", "diagnose", "sources", "policy", "approval", "execution", "outcome"))}
    assert steps["B2"]["screen"] == {"layer": "llm", "p_injection": 0.03, "decision": "safe"}
    assert steps["B3"]["classify"] == {
        "intent": "vpn", "confidence": 0.95, "model_probs": {"vpn": 0.97, "account": 0.02},
        "model_version": "intent-clf@1", "is_multi": False,
    }  # fmt: skip
    assert steps["B6"]["diagnose"] == {"fact_keys": ["cert_expired", "device_registered"]}
    assert steps["B10"]["sources"] == []
    assert steps["B13/B14"]["policy"] == {
        "rule_id": "R18", "rule_description": RULES["R18"].description, "policy_decision": "approval_required",
        "risk_level": "medium", "decided_by": "rule", "raw_prob": None, "calibrated_prob": None,
        "matched_rules": [{"rule_id": "R18", "description": RULES["R18"].description, "decision": "approval_required",
                           "applied": True}],
    }  # fmt: skip
    assert steps["B15"]["approval"] == {
        "approver_id": "l1_01", "approver_name": "Lê Thu Hà", "result": "pending", "at": "2099-09-26T08:09:00Z",
    }  # fmt: skip
    assert steps["B16"]["approval"] == {
        "approver_id": "l1_01", "approver_name": "Lê Thu Hà", "result": "approved", "at": "2099-09-26T08:10:00Z",
    }  # fmt: skip
    assert steps["B18"]["execution"] == {
        "action": "renew_vpn_cert", "success": True, "rollback_status": "none_needed",
        "calls": [{"name": "renew_vpn_cert", "result": "ok"}],
    }  # fmt: skip
    assert steps["B20"]["outcome"] == {"route": "approved", "exit_code": None}


def test_steps_sorted_by_time() -> None:
    rows = vpn_audit()[::-1]
    out = build_trace(TraceData(TicketHead("T", "u", None, False), rows), RULES)
    assert [s.step for s in out.steps][:3] == ["B1", "B2", "B3"]


def test_probabilities_rounded_to_two_digits() -> None:
    rows = [
        _row(1, "B2", "injection_detected", detail={"screening": {"layer_decided": "classifier", "p_mal": 0.98765}}),
        _row(2, "B3", "intent_classified", detail={"confidence": 0.94449, "model_probs": {"vpn": 0.96666}}),
        _row(3, "B13/B14", "risk_decided", decided_by="llm", risk_level="low", raw_prob=0.12345, calibrated_prob=0.08765),
    ]
    out = build_trace(TraceData(TicketHead("T", "u", None, False), rows), RULES)
    screen, classify, policy = out.steps[0].screen, out.steps[1].classify, out.steps[2].policy
    assert screen is not None and (screen.layer, screen.p_injection, screen.decision) == ("model", 0.99, "attack")
    assert classify is not None and (classify.confidence, classify.model_probs) == (0.94, {"vpn": 0.97})
    assert policy is not None and (policy.raw_prob, policy.calibrated_prob) == (0.12, 0.09)
    assert policy.decided_by == "llm" and policy.rule_id is None and policy.rule_description is None


@pytest.mark.parametrize("bad", [1.5, -0.1, float("nan"), True, "0.5", None])
def test_bad_probability_dropped(bad: Any) -> None:
    rows = [_row(1, "B13/B14", "risk_decided", decided_by="llm", raw_prob=bad)]
    policy = build_trace(TraceData(TicketHead("T", "u", None, False), rows), RULES).steps[0].policy
    assert policy is not None and policy.raw_prob is None


def test_missing_fields_do_not_fail() -> None:
    """Mọi bước với `detail` rỗng / sai kiểu và không cột phụ → 200 với None/rỗng."""
    rows = [_row(i, s, "x", detail=d) for i, (s, d) in enumerate([
        ("B2", {}), ("B3", {"model_probs": "x"}), ("B6", {"facts": ["a"]}), ("B10", {"cited": "x"}), ("B13/B14", {}),
        ("B15", {}), ("B16", {}), ("B17", {"steps_done": "x"}), ("B20", None),
    ])]  # fmt: skip
    out = build_trace(TraceData(TicketHead("T", "u", None, False), rows), {})
    assert len(out.steps) == 9
    assert out.steps[0].screen is not None and out.steps[0].screen.decision is None
    assert out.steps[1].classify is not None and out.steps[1].classify.model_probs is None
    assert out.steps[2].diagnose is not None and out.steps[2].diagnose.fact_keys == []
    assert out.steps[3].sources == []
    assert out.steps[5].approval is not None and out.steps[5].approval.approver_id is None
    assert out.steps[7].execution is not None and out.steps[7].execution.calls == []
    assert out.steps[8].outcome is not None and out.steps[8].outcome.route is None


def test_kb_sources_with_titles() -> None:
    rows = [_row(1, "B10", "deflected_info_only", detail={
        "cited": ["KB-VPN-001#v3#0", "KB-VPN-001#v3#2", "KB-VPN-007#v1#4", f"{USER_TEXT}#v1#1"],
    })]  # fmt: skip
    data = TraceData(TicketHead("T", "u", None, False), rows, kb_titles={("KB-VPN-001", 3): "Gia hạn chứng chỉ VPN"})
    assert api.cited_docs(rows) == [("KB-VPN-001", 3), ("KB-VPN-007", 1)]
    sources = build_trace(data, {}).steps[0].sources
    assert [s.model_dump() for s in sources or []] == [
        {"doc_id": "KB-VPN-001", "title": "Gia hạn chứng chỉ VPN"}, {"doc_id": "KB-VPN-007", "title": None},
    ]


def test_execution_failure_and_action_type_only() -> None:
    rows = [
        _row(1, "B11", "action_built", intended_action={"type": "unlock_account", "params": {"user_id": CANARY}}),
        _row(2, "B17", "exec_failed", detail={
            "success": False, "steps_done": ["ad_unlock"], "failed_step": "ad_reset", "rollback_status": "undone",
        }),
    ]
    ex = build_trace(TraceData(TicketHead("T", "u", None, False), rows), {}).steps[1].execution
    assert ex is not None and ex.model_dump() == {
        "action": "unlock_account", "success": False, "rollback_status": "undone",
        "calls": [{"name": "ad_unlock", "result": "ok"}, {"name": "ad_reset", "result": "failed"}],
    }  # fmt: skip


def test_rejected_and_timeout_approvals() -> None:
    rows = [
        _row(1, "B15", "queued", approver_id="l1_01"),
        _row(2, "B16", "rejected", approval_result="rejected", note=CANARY),
        _row(3, "B15", "queued", approver_id="l1_02"),
        _row(4, "B16", "approval_timeout", approval_result="timeout"),
    ]
    approvals = [
        {"approval_id": 1, "approver_id": "l1_01", "decided_by": "l1_01", "decided_at": _at(2), "created_at": _at(1)},
        {"approval_id": 2, "approver_id": "l1_02", "decided_by": None, "decided_at": None, "created_at": _at(3)},
    ]
    out = build_trace(TraceData(TicketHead("T", "u", None, False), rows, approvals=approvals), {})
    got = [(a.approver_id, a.result, a.at) for s in out.steps if (a := s.approval) is not None]
    assert got == [("l1_01", "pending", _at(1)), ("l1_01", "rejected", _at(2)), ("l1_02", "pending", _at(3)),
                   ("l1_02", "timeout", _at(4))]  # fmt: skip
    assert CANARY not in out.model_dump_json()


def test_parent_lists_children_and_child_links_parent(env: AuthEnv) -> None:
    body = _get(env, "P-1", env.token("ha.lt")).json()
    assert body["is_parent"] is True and body["parent_ticket_id"] is None
    assert body["children"] == [
        {"ticket_id": "P-1-1", "intent": "vpn", "exit_code": None},
        {"ticket_id": "P-1-2", "intent": "account", "exit_code": "E1"},
    ]
    assert body["steps"][0]["classify"]["is_multi"] is True
    child = _get(env, "P-1-1", env.token("ha.lt")).json()
    assert child["is_parent"] is False and child["parent_ticket_id"] == "P-1" and child["children"] == []


def test_openapi_declares_trace_model(env: AuthEnv) -> None:
    spec = env.app.openapi()
    op = spec["paths"]["/api/tickets/{ticket_id}/trace"]["get"]
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/TicketTrace"}
    assert {"401", "403", "404", "503"} <= set(op["responses"])
    schemas = spec["components"]["schemas"]
    assert set(schemas["TraceStep"]["required"]) == {
        "step", "event", "at", "screen", "classify", "diagnose", "sources", "policy", "approval", "execution", "outcome",
    }
    assert schemas["TicketTrace"]["additionalProperties"] is False


# ---- lô N (N7): thẻ B20 `escalation_closed` có kết quả đóng ca -------------------------------------------------------------


def _closed_row(close_result: Any) -> dict[str, Any]:
    """Dòng audit đóng ca đúng khuôn `db/escalations.close_audit_row` (detail {escalation_id, close_result, closed_by, note_length})."""
    return _row(1, "B20", "escalation_closed", exit_code=None, detail={
        "escalation_id": 7, "close_result": close_result, "closed_by": "long.nh", "note_length": 42,
    })  # fmt: skip


@pytest.mark.parametrize("result", ["completed", "confirmed_denial", "reopened_as_new"])
def test_n7_escalation_closed_has_close_result(result: str) -> None:
    outcome = build_trace(TraceData(TicketHead("T", "u", None, False), [_closed_row(result)]), {}).steps[0].outcome
    assert outcome is not None
    assert outcome.model_dump(exclude_unset=True) == {"route": None, "exit_code": None, "close_result": result}


@pytest.mark.parametrize("bad", ["closed_ok", "", 1, None, ["completed"], f"{CANARY} completed"])
def test_n7_escalation_closed_unknown_value_is_null(bad: Any) -> None:
    outcome = build_trace(TraceData(TicketHead("T", "u", None, False), [_closed_row(bad)]), {}).steps[0].outcome
    assert outcome is not None
    assert outcome.model_dump(exclude_unset=True) == {"route": None, "exit_code": None, "close_result": None}


def test_n7_escalation_closed_route_no_closed_by(env: AuthEnv, source: FakeTrace) -> None:
    """Qua route: khoá `close_result` có mặt; KHÔNG `closed_by`, `note_length`, `escalation_id`."""
    source.items["C-1"] = TraceData(TicketHead("C-1", "nv001", None, False), [_closed_row("confirmed_denial")])
    r = _get(env, "C-1", env.manager_token())
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]
    assert step["outcome"] == {"route": None, "exit_code": None, "close_result": "confirmed_denial"}
    assert "long.nh" not in str(step) and "note_length" not in str(step) and "escalation_id" not in str(step)


def test_n7_plain_b20_unchanged() -> None:
    """B20 thường (không phải `escalation_closed`) — không gán `close_result` (route bỏ khoá); `detail.close_result` bị lờ."""
    row = _row(1, "B20", "ticket_closed", exit_code="E5", detail={"resolution_path": "escalated", "close_result": "completed"})
    outcome = build_trace(TraceData(TicketHead("T", "u", None, False), [row]), {}).steps[0].outcome
    assert outcome is not None
    assert outcome.model_dump(exclude_unset=True) == {"route": "escalated", "exit_code": "E5"}
