"""P3 tuần 8 — `matched_rules` (mọi luật khớp ở B13/B14) cho trace (khối `policy` của bước B13/B14) và màn duyệt (gốc `ApprovalView`).

Hợp đồng: nguồn `detail.all_matched` + `matched_rule_id` của dòng B13/B14; thứ tự giữ như `all_matched`; `decision`/`description` tra
`rule_id` trong chính sách đang áp dụng (MỘT hàm `rule_index` cho cả hai route); đúng một `applied` khi luật quyết định nằm trong
danh sách; không luật nào khớp → []; chưa tới B13/B14 → KHÔNG có khoá; chỉ L1/L2/manager — route của nhân viên không trả trường này.
Quyết định cuối không do luật (hybrid_guarded + lỗi AI → E5 `llm_layer_disabled`) → 0 phần tử `applied` (hợp đồng mục 3 cho phép).
Điểm lệch BE: luật đã bị xoá khỏi chính sách → `decision`/`description` null (Q10). Dòng không có `all_matched` (full_auto, B12 giả) → bỏ
khoá (Q12, BE duyệt).

Mã luật và mô tả đều GIẢ (R81…R84); chính sách giả thay `get_policy` của `api/matched_rules.py` — trace và màn duyệt cùng thấy nó.
"""

from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from app.api import matched_rules as mr
from app.api.matched_rules import MatchedRule, RuleRef, matched_rules
from app.api.trace import TicketHead, TraceData
from app.auth.permissions import PERMS
from app.core.clock import FakeClock
from app.main import create_app
from tests.fakes.auth import EPOCH
from tests.fakes.desk import DeskEnv, desk_env
from tests.unit.auth_helpers import AuthEnv, auth_env, auth_settings
from tests.unit.test_approvals_view import _login, _pending, _row, _view
from tests.unit.test_auth_route_scan import route_auth
from tests.unit.test_trace_api import URL, FakeTrace
from tests.unit.test_trace_api import _row as _audit

POLICY = SimpleNamespace(rules=[
    SimpleNamespace(id="R81", type="allow", description="Mô tả giả R81"),
    SimpleNamespace(id="R82", type="approval_required", description="Mô tả giả R82"),
    SimpleNamespace(id="R83", type="deny", description="Mô tả giả R83"),
])  # fmt: skip
INDEX = {
    "R81": RuleRef("allow", "Mô tả giả R81"), "R82": RuleRef("approval_required", "Mô tả giả R82"),
    "R83": RuleRef("deny", "Mô tả giả R83"),
}  # fmt: skip
R82_R81_R83 = [
    {"rule_id": "R82", "description": "Mô tả giả R82", "decision": "approval_required", "applied": False},
    {"rule_id": "R81", "description": "Mô tả giả R81", "decision": "allow", "applied": False},
    {"rule_id": "R83", "description": "Mô tả giả R83", "decision": "deny", "applied": True},
]  # fmt: skip


@pytest.fixture(autouse=True)
def _fake_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mr, "get_policy", lambda: POLICY)


def _dump(rules: list[MatchedRule] | None) -> list[dict[str, Any]] | None:
    return None if rules is None else [r.model_dump() for r in rules]


# ---- hàm thuần ------------------------------------------------------------------------------------------------------------------


def test_rule_index_reads_running_policy() -> None:
    assert mr.rule_index() == INDEX


def test_many_matched_keep_order_and_exactly_one_applied() -> None:
    out = _dump(matched_rules(["R82", "R81", "R83"], "R83", INDEX))
    assert out == R82_R81_R83
    assert out is not None and sum(r["applied"] for r in out) == 1


def test_no_rule_matched_is_empty_list() -> None:
    assert matched_rules([], None, INDEX) == []


@pytest.mark.parametrize("raw", [None, "R81", {"R81": True}, 3])
def test_all_matched_not_a_list_means_no_key(raw: Any) -> None:
    assert matched_rules(raw, "R81", INDEX) is None


def test_rule_removed_from_policy_has_null_decision_and_description() -> None:
    """Điểm lệch BE Q10: luật không còn trong chính sách đang áp dụng — giữ phần tử, không đoán quyết định."""
    assert _dump(matched_rules(["R84", "R81"], "R84", INDEX)) == [
        {"rule_id": "R84", "description": None, "decision": None, "applied": True},
        {"rule_id": "R81", "description": "Mô tả giả R81", "decision": "allow", "applied": False},
    ]  # fmt: skip


def test_matched_but_no_deciding_rule_all_applied_false() -> None:
    """Quyết định cuối không do luật (hybrid_guarded + lỗi AI, `matched_rule_id` null) → 0 phần tử applied (hợp đồng mục 3)."""
    out = _dump(matched_rules(["R81"], None, INDEX))
    assert out == [{"rule_id": "R81", "description": "Mô tả giả R81", "decision": "allow", "applied": False}]


def test_non_identifier_entries_dropped() -> None:
    out = _dump(matched_rules(["R81", "câu chữ người dùng có dấu cách", 7, None], "R81", INDEX))
    assert out is not None and [r["rule_id"] for r in out] == ["R81"]


# ---- trace ----------------------------------------------------------------------------------------------------------------------


def _b13(i: int, all_matched: Any = ..., matched_rule_id: str | None = "R83", **cols: Any) -> dict[str, Any]:
    detail: dict[str, Any] = {"route": "ESCALATE_L2"}
    if all_matched is not ...:
        detail["all_matched"] = all_matched
    cols = {"decided_by": "rule", "policy_decision": "deny", "risk_level": "high", **cols}
    return _audit(i, "B13/B14", "risk_decided", matched_rule_id=matched_rule_id, detail=detail, **cols)


def _ticket(tid: str, *rows: dict[str, Any]) -> TraceData:
    return TraceData(ticket=TicketHead(tid, "nv001", None, False), audit=[_audit(1, "B1", "identity_established"), *rows])


@pytest.fixture
def trace_env() -> Iterator[AuthEnv]:
    source = FakeTrace(
        _ticket("T-MANY", _b13(2, ["R82", "R81", "R83"])),
        _ticket("T-NONE", _b13(2, [], None, decided_by="llm", policy_decision=None)),
        _ticket("T-EARLY", _audit(2, "B3", "intent_classified")),
        _ticket("T-NOLIST", _b13(2)),
        _ticket("T-GUARDED", _b13(2, ["R81"], None, decided_by="llm", policy_decision=None)),
    )  # fmt: skip
    with auth_env(clock=FakeClock(EPOCH)) as e:
        e.app.state.trace = source
        yield e


def _trace(env: AuthEnv, tid: str, token: str) -> Any:
    r = env.client.get(URL.format(tid), headers=env.bearer(token))
    assert r.status_code == 200, r.text
    return r


def _policy_step(body: dict[str, Any]) -> dict[str, Any]:
    [step] = [s for s in body["steps"] if s["step"] == "B13/B14"]
    return dict(step["policy"])


@pytest.mark.parametrize("who", ["l1", "l2", "manager"])
def test_trace_many_matched_in_policy_block(trace_env: AuthEnv, who: str) -> None:
    token = {"l1": lambda: trace_env.token("ha.lt"), "l2": lambda: trace_env.token("long.nh"),
             "manager": trace_env.manager_token}[who]()  # fmt: skip
    policy = _policy_step(_trace(trace_env, "T-MANY", token).json())
    assert policy["matched_rules"] == R82_R81_R83
    assert policy["rule_id"] == "R83" and policy["rule_description"] == "Mô tả giả R83"  # CÙNG nguồn mô tả


def test_trace_no_rule_matched_is_empty_list(trace_env: AuthEnv) -> None:
    assert _policy_step(_trace(trace_env, "T-NONE", trace_env.token("ha.lt")).json())["matched_rules"] == []


def test_trace_before_b13_has_no_key(trace_env: AuthEnv) -> None:
    r = _trace(trace_env, "T-EARLY", trace_env.token("ha.lt"))
    assert "matched_rules" not in r.text
    assert all(s["policy"] is None for s in r.json()["steps"])


def test_trace_b13_row_without_all_matched_drops_key(trace_env: AuthEnv) -> None:
    """Điểm lệch BE Q12: dòng B13/B14 không chạy luật (full_auto, B12 giả) — bỏ khoá, không trả [] (= "không luật nào khớp")."""
    policy = _policy_step(_trace(trace_env, "T-NOLIST", trace_env.token("ha.lt")).json())
    assert "matched_rules" not in policy
    assert set(policy) == {"rule_id", "rule_description", "policy_decision", "risk_level", "decided_by", "raw_prob",
                           "calibrated_prob"}  # fmt: skip


def test_trace_guarded_no_applied(trace_env: AuthEnv) -> None:
    policy = _policy_step(_trace(trace_env, "T-GUARDED", trace_env.token("ha.lt")).json())
    assert policy["matched_rules"] == [
        {"rule_id": "R81", "description": "Mô tả giả R81", "decision": "allow", "applied": False},
    ]  # fmt: skip


def test_trace_employee_forbidden(trace_env: AuthEnv) -> None:
    r = trace_env.client.get(URL.format("T-MANY"), headers=trace_env.bearer(trace_env.token("an.nv")))
    assert r.status_code == 403 and "matched_rules" not in r.text


# ---- màn duyệt (gốc ApprovalView) -------------------------------------------------------------------------------------------------


def _b13_row(env: DeskEnv, ticket: str) -> dict[str, Any]:
    [row] = [r for r in env.h.audit.rows if (r["ticket_id"], r["step"]) == (ticket, "B13/B14")]
    return row


def _set_matches(row: dict[str, Any], all_matched: list[str], applied: str | None) -> None:
    row["detail"] = {**(row.get("detail") or {}), "all_matched": all_matched}
    row["matched_rule_id"] = applied


@pytest.mark.asyncio
async def test_approval_view_matched_rules_at_root() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        _set_matches(_b13_row(env, ticket), ["R82", "R81", "R83"], "R83")
        body = (await _view(env, aid, await _login(env, "ha.lt"))).json()
        assert body["matched_rules"] == R82_R81_R83
        assert "policy" not in body


@pytest.mark.asyncio
async def test_approval_view_uses_assessment_before_the_approval() -> None:
    """Dòng B13/B14 ghi SAU lúc tạo phiếu (đánh giá lại) không phải căn cứ của phiếu này."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        row = _b13_row(env, ticket)
        _set_matches(row, ["R81"], "R81")
        later = {**row, "detail": {"all_matched": ["R83"]}, "matched_rule_id": "R83",
                 "created_at": _row(env, aid)["created_at"] + timedelta(minutes=1)}  # fmt: skip
        env.h.audit.rows.append(later)
        body = (await _view(env, aid, await _login(env, "ha.lt"))).json()
        assert body["matched_rules"] == [{"rule_id": "R81", "description": "Mô tả giả R81", "decision": "allow", "applied": True}]


@pytest.mark.asyncio
async def test_approval_view_no_rule_matched_is_empty_list() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        _set_matches(_b13_row(env, ticket), [], None)
        assert (await _view(env, aid, await _login(env, "ha.lt"))).json()["matched_rules"] == []


@pytest.mark.asyncio
async def test_approval_view_without_all_matched_has_no_key() -> None:
    """B12 giả (desk_env) không ghi `all_matched` → không có khoá (Q12); mọi khoá khác giữ nguyên."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        r = await _view(env, aid, await _login(env, "ha.lt"))
        assert r.status_code == 200 and "matched_rules" not in r.json()


# ---- vai nhân viên không bao giờ thấy trường này ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_employee_ticket_view_has_no_matched_rules() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        _set_matches(_b13_row(env, ticket), ["R82", "R81", "R83"], "R83")
        an = await _login(env, "an.nv")
        r = await env.client.get(f"/api/tickets/{ticket}", headers=an)
        assert r.status_code == 200 and "matched_rules" not in r.text and "R81" not in r.text
        assert (await _view(env, aid, an)).status_code == 403


def _props(spec: dict[str, Any], node: Any, seen: set[str]) -> Iterator[str]:
    """Mọi tên thuộc tính trong schema (đi theo `$ref`, `items`, `anyOf`…)."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                yield from _props(spec, spec["components"]["schemas"][name], seen)
        yield from node.get("properties", {})
        for v in node.values():
            yield from _props(spec, v, seen)
    elif isinstance(node, list):
        for v in node:
            yield from _props(spec, v, seen)


def _response_props(spec: dict[str, Any], path: str, method: str) -> set[str]:
    responses = spec["paths"][path][method.lower()].get("responses", {})
    return set(_props(spec, responses, set()))


def test_no_employee_route_declares_matched_rules() -> None:
    """Quét ĐỘNG: mọi route nhân viên gọi được (permission thuộc PERMS["employee"], hoặc chỉ cần đăng nhập) — schema trả về không có
    `matched_rules`. Đối chứng: trace và màn duyệt CÓ trường này (phép quét không rỗng)."""
    app = create_app(auth_settings(), health_checks={})
    spec = app.openapi()
    employee = PERMS["employee"]
    checked = []
    for c in route_auth(app):
        reachable = any((perm is None or perm in employee) and (roles is None or "employee" in roles)
                        for perm, roles, _ in c.requirements)  # fmt: skip
        if not reachable or c.path not in spec["paths"]:
            continue
        for m in c.methods:
            assert "matched_rules" not in _response_props(spec, c.path, m), (m, c.path)
            checked.append((m, c.path))
    assert ("GET", "/api/tickets/{ticket_id}") in checked
    assert "matched_rules" in _response_props(spec, "/api/tickets/{ticket_id}/trace", "GET")
    assert "matched_rules" in _response_props(spec, "/api/approvals/{approval_id}", "GET")
