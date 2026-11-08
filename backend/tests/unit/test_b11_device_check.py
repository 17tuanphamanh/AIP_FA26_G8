"""Q2 M4 (ĐP 09/11) — B11, intent vpn, có slot `device_id` mà B6 ĐÃ tra đúng máy đó (fact `device_registered` có mặt), TRƯỚC khi hỏi:

- máy TỒN TẠI và `device_owner_is_requester is False` → KHÔNG hỏi hành động; E5 `approval_target_unverified` ngay ở B11, audit
  `owner_mismatch_early=true`. Bằng chứng (c): "Máy LAP-0610 của chị Hoa…" → bot hỏi "cấp mới, gia hạn…" rồi mới bị chốt ở B15.
- máy KHÔNG tồn tại (`check_device_registered` 404 → `diagnostics` không có máy) → bỏ slot `device_id` + fact máy cũ, hỏi MỘT câu CỐ
  ĐỊNH (không LLM; output guard + notify + hạn như `TARGET_QUESTION`). Bằng chứng (d): "Máy LAP-0012 của mình…" (gõ nhầm) → E5 ngay.
  Máy trả lời sau đó không do B6 tra → luồng cũ (không hỏi lại lần 2).
Ca khác (máy của mình, B6 chưa tra máy này, intent khác, đủ slot) giữ nguyên.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.messages import device_not_found_question
from app.domain.states import S_ASSESSING, S_CLARIFYING, S_ESCALATED, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.late_event import deliver_event
from app.graph.nodes import b11_slots
from app.llm.providers.scripted import Script
from app.rag.models import RetrievalResult
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts

NOT_FOUND = ("Mình không tìm thấy máy LAP-0012 trong danh mục. Bạn xem mã máy dán ở thân máy (dạng LAP-0342) rồi gửi lại "
             "giúp mình.")  # fmt: skip
DEV_0610 = {"device_id": "LAP-0610", "owner_id": "nv005", "kind": "laptop", "os": "macOS 15", "registered": True,
            "registered_at": "2025-10-01T00:00:00Z"}  # fmt: skip
DEV_0342 = {"device_id": "LAP-0342", "owner_id": "nv001", "kind": "laptop", "os": "Windows 11", "registered": True,
            "registered_at": "2024-01-01T00:00:00Z"}  # fmt: skip
OTHER_FACTS: dict[str, Any] = {"device_registered": True, "device_owner_is_requester": False, "cert_status": "none",
                               "last_connection_ok": False}  # fmt: skip
GONE_FACTS: dict[str, Any] = {"device_registered": False, "device_owner_is_requester": False, "cert_status": "none",
                              "last_connection_ok": False}  # fmt: skip


def test_question_text_fixed_and_id_only_when_pattern_matches() -> None:
    assert device_not_found_question("LAP-0012") == NOT_FOUND
    assert device_not_found_question("lap 0012<b>") == (
        "Mình không tìm thấy máy này trong danh mục. Bạn xem mã máy dán ở thân máy (dạng LAP-0342) rồi gửi lại giúp mình."
    )


# ---- node gọi trực tiếp -------------------------------------------------------------------------------------------------


def _ctx(user: str = "nv001") -> RequesterContext:
    return RequesterContext(
        user_id=user, role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=100, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _state(slots: dict[str, str], facts: dict[str, Any], devices: list[dict[str, Any]] | None, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "intent": "vpn", "slots": slots,
                            "facts": facts, "requester_context": _ctx(), "redacted_request": "VPN không vào được",
                            "clarification_turns": 0, "diagnostics": {"check_device_registered": devices,
                                                                      "check_vpn_cert_expiry": None,
                                                                      "check_last_connection": None}}  # fmt: skip
    base.update(over)
    return base


def _harness(**scripts: Script) -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    gw = make_gateway({**vpn_scripts(), **scripts}, clock=clock)  # type: ignore[arg-type]
    return GraphHarness(clock=clock, llm=gw.client), gw


@contextmanager
def _run(h: GraphHarness) -> Iterator[None]:
    with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=h.audit, effects=h.effects, spans=h.spans,
                             clock=h.clock, txlog=h.txlog)):  # fmt: skip
        yield


async def _node(h: GraphHarness, state: dict[str, Any], **deps_over: Any) -> dict[str, Any]:
    deps = h.deps()
    for k, v in deps_over.items():
        setattr(deps, k, v)
    with _run(h):
        return await b11_slots.make(deps)(state)


def _detail(h: GraphHarness) -> dict[str, Any]:
    [row] = [r for r in h.audit.rows if r["step"] == "B11"]
    return dict(row["detail"])


@pytest.mark.asyncio
async def test_other_persons_device_e5_now_no_question() -> None:
    h, gw = _harness()
    out = await _node(h, _state({"device_id": "LAP-0610"}, OTHER_FACTS, [DEV_0610]))
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (
        S_ESCALATED, "E5", "approval_target_unverified",
    )  # fmt: skip
    assert out["next"] == "b20_audit" and "clarification_turns" not in out and "conversation" not in out
    assert gw.llm.calls == [] and h.notifier.sent == [] and h.deadlines.waits == []
    [row] = [r for r in h.audit.rows if r["step"] == "B11"]
    assert row["event"] == "approval_target_unverified"
    assert (row["detail"]["owner_mismatch_early"], row["detail"]["device_not_found"]) == (True, False)
    assert "LAP-0610" not in repr(row["detail"])


@pytest.mark.asyncio
async def test_unknown_device_asks_fixed_question_once_drops_slot_and_device_facts() -> None:
    h, gw = _harness()
    out = await _node(h, _state({"device_id": "LAP-0012"}, GONE_FACTS, None))
    assert (out["status"], out["next"], out["clarification_turns"]) == (S_CLARIFYING, "clarify_wait", 1)
    assert gw.llm.calls == []  # câu cố định — không gọi LLM
    [(ticket, text, needs)] = h.notifier.sent
    assert (ticket, text, needs) == ("t1", NOT_FOUND, "answer")
    [q] = out["conversation"]
    assert (q["kind"], q["text"]) == ("question", NOT_FOUND)
    [wait] = h.deadlines.waits
    assert (wait["kind"], wait["deadline"] - h.clock.now()) == ("clarify", timedelta(hours=24))
    assert out["slots"] == {}  # bỏ mã máy không có thật
    assert out["facts"] == {"last_connection_ok": False}  # fact máy cũ bỏ, fact theo người giữ
    assert out["missing_slots"] == ["device_id", "action"]
    detail = _detail(h)
    assert (detail["device_not_found"], detail["owner_mismatch_early"], detail["prompt"]) == (True, False, None)
    assert detail["missing"] == ["device_id", "action"]
    assert "LAP-0012" not in repr(h.audit.rows)


@pytest.mark.asyncio
async def test_unknown_device_keeps_user_action_slot() -> None:
    """Có `action` mà thiếu slot khác thì không tới được đây ở VPN; kiểm thêm: slot khác ngoài `device_id` được giữ."""
    h, _ = _harness()
    out = await _node(h, _state({"device_id": "LAP-0012", "error_code": "809"}, GONE_FACTS, None))
    assert out["slots"] == {"error_code": "809"} and out["missing_slots"] == ["device_id", "action"]


class _BlockId:
    def violation(self, text: str) -> str | None:
        return "secret" if "LAP-0012" in text else None


@pytest.mark.asyncio
async def test_fixed_question_goes_through_output_guard() -> None:
    h, _ = _harness()
    out = await _node(h, _state({"device_id": "LAP-0012"}, GONE_FACTS, None), output_guard=_BlockId())
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E3", "output_guard_block")
    assert h.notifier.sent == [] and h.deadlines.waits == []


@pytest.mark.asyncio
async def test_unknown_device_after_last_turn_is_e4_as_before() -> None:
    h, gw = _harness()
    turns = h.deps().constants.MAX_CLARIFICATION_TURNS
    out = await _node(h, _state({"device_id": "LAP-0012"}, GONE_FACTS, None, clarification_turns=turns))
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E4", "clarification_exhausted")
    assert gw.llm.calls == [] and h.notifier.sent == []


@pytest.mark.parametrize(("why", "slots", "facts", "devices", "intent"), [
    ("may-cua-minh", {"device_id": "LAP-0342"}, {**OTHER_FACTS, "device_owner_is_requester": True}, [DEV_0342], "vpn"),
    # B6 tra theo người (2 máy), mã máy có từ câu trả lời → B6 chưa tra máy này: không suy "không tồn tại"/"người khác"
    ("b6-chua-tra-may-nay", {"device_id": "LAP-0012"}, {"device_count": 2, "has_registered_device": True}, None, "vpn"),
    ("b6-tra-theo-nguoi-suy-may", {"device_id": "LAP-0342"},
     {"device_count": 1, "has_registered_device": True, "device_registered": True, "device_owner_is_requester": True,
      "cert_status": "valid"}, [DEV_0342], "vpn"),
    ("fact-cu-khong-khop-danh-sach-theo-nguoi", {"device_id": "LAP-0012"},
     {"device_count": 1, "has_registered_device": True, **GONE_FACTS}, [DEV_0342], "vpn"),
    ("tat-chan-doan", {"device_id": "LAP-0610"}, {}, None, "vpn"),
    ("intent-khac", {"device_id": "LAP-0610"}, OTHER_FACTS, [DEV_0610], "software"),
])  # fmt: skip
@pytest.mark.asyncio
async def test_other_cases_ask_with_llm_as_before(
    why: str, slots: dict[str, str], facts: dict[str, Any], devices: list[dict[str, Any]] | None, intent: str
) -> None:
    h, gw = _harness()
    out = await _node(h, _state(slots, facts, devices, intent=intent))
    assert out["status"] == S_CLARIFYING, why
    assert len(gw.llm.calls_for("b11_clarify_question")) == 1, why
    assert "slots" not in out and "facts" not in out, why
    detail = _detail(h)
    assert (detail["owner_mismatch_early"], detail["device_not_found"]) == (False, False), why


@pytest.mark.asyncio
async def test_full_slots_other_persons_device_build_path_unchanged() -> None:
    """Máy của người khác ở đường đủ slot: GIỮ luồng cũ (`validate_targets` + `build_action` → B12/B15 chốt P6) — ĐP 09/11 điểm 1."""
    h, gw = _harness()
    out = await _node(h, _state({"device_id": "LAP-0610", "action": "renew_vpn_cert"}, OTHER_FACTS, [DEV_0610]))
    assert out["status"] == S_ASSESSING and out["intended_action"].params["device_id"] == "LAP-0610"
    assert gw.llm.calls == [] and h.notifier.sent == []
    assert _detail(h)["device_not_found"] is False


@pytest.mark.asyncio
async def test_full_slots_unknown_device_asks_fixed_question_no_action() -> None:
    """ĐP 09/11 điểm 1 — bằng chứng (d) có gợi ý hành động sẵn: đủ slot mà máy 404 (B6 đã tra) → hỏi lại mã như M4, KHÔNG dựng
    Action, không gọi tool kiểm lại; giữ slot `action`."""
    h, gw = _harness()
    out = await _node(h, _state({"device_id": "LAP-0012", "action": "check_vpn_status"}, GONE_FACTS, None))
    assert (out["status"], out["next"], out["clarification_turns"]) == (S_CLARIFYING, "clarify_wait", 1)
    assert "intended_action" not in out and gw.llm.calls == []
    assert h.vpn is None or sum(h.vpn.calls.values()) == 0  # validate_targets không chạy
    assert h.notifier.sent == [("t1", NOT_FOUND, "answer")]
    assert out["slots"] == {"action": "check_vpn_status"} and out["facts"] == {"last_connection_ok": False}
    assert out["missing_slots"] == ["device_id"]
    detail = _detail(h)
    assert (detail["device_not_found"], detail["missing"], detail["tools_called"]) == (True, ["device_id"], [])
    [row] = [r for r in h.audit.rows if r["step"] == "B11"]
    assert row["event"] == "asked"


@pytest.mark.asyncio
async def test_full_slots_unknown_device_after_last_turn_is_e4() -> None:
    h, gw = _harness()
    turns = h.deps().constants.MAX_CLARIFICATION_TURNS
    out = await _node(h, _state({"device_id": "LAP-0012", "action": "check_vpn_status"}, GONE_FACTS, None,
                                clarification_turns=turns))  # fmt: skip
    assert (out["exit_code"], out["escalation_reason_detail"], out["missing_slots"]) == (
        "E4", "clarification_exhausted", ["device_id"],
    )  # fmt: skip
    assert gw.llm.calls == [] and h.notifier.sent == []


# ---- graph thật B1 → … → B6 → B8 → B10 → B11 (VPN giả đọc seed) ---------------------------------------------------------


def _rag() -> FakeRag:
    chunk = ChunkRef(chunk_id="c1", doc_id="KB-VPN-004", version=1, seq=0, title="T", heading_path="H",
                     score=0.99, excerpt="x")  # fmt: skip
    return FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.99, kb_version="a" * 64,
                                          intent_filter_fallback=False, fallback_tried=False, retries=0,
                                          query_truncated=False))  # fmt: skip


def _graph(user: str = "nv001", action: str | None = None) -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    gw = make_gateway(vpn_scripts(need="action", action=action), clock=clock)  # type: ignore[arg-type]
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=_rag(), ad=FakeAd(ad_user(user)))
    h.identity.add_session(f"s-{user}", user, expires_at=clock.now() + timedelta(days=365))
    h.tickets.register("t1", clock.now(), requester_id=user)
    return h, gw


async def _submit(h: GraphHarness, text: str, user: str = "nv001") -> dict[str, Any]:
    return cast(dict[str, Any], (await h.runner.submit("t1", session_id=f"s-{user}", redacted_request=text)).values)


async def _reply(h: GraphHarness, text: str) -> dict[str, Any]:
    return cast(dict[str, Any], (await deliver_event(h.runner, "t1", S_CLARIFYING,
                                                     {"kind": "user_reply", "text": text})).values)  # fmt: skip


def _asked(h: GraphHarness) -> list[str]:
    return [t for _, t, n in h.notifier.sent if n == "answer"]


@pytest.mark.asyncio
async def test_graph_hoa_device_escalates_e5_without_asking_action() -> None:
    h, gw = _graph()
    v = await _submit(h, "Máy LAP-0610 của chị Hoa không vào VPN xử lý giúp")
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E5", "approval_target_unverified")
    assert gw.llm.calls_for("b11_clarify_question") == [] and _asked(h) == []
    [row] = h.audit.of("t1", "approval_target_unverified")
    assert (row["step"], row["detail"]["owner_mismatch_early"]) == ("B11", True)


@pytest.mark.asyncio
async def test_graph_typo_device_asked_once_then_correct_code_continues() -> None:
    h, gw = _graph()
    v = await _submit(h, "Máy LAP-0012 của mình không vào được VPN")
    assert v["status"] == S_CLARIFYING and _asked(h) == [NOT_FOUND]
    assert gw.llm.calls_for("b11_clarify_question") == []
    v = await _reply(h, "LAP-0342, kiểm tra giúp mình")
    action = v["intended_action"]
    assert (action.type, action.params["device_id"]) == ("check_vpn_status", "LAP-0342")
    assert action.facts["device_owner_is_requester"] is True and action.facts["cert_status"] == "expired"
    assert _asked(h) == [NOT_FOUND]  # không hỏi thêm


@pytest.mark.asyncio
async def test_graph_second_unknown_code_falls_back_to_old_flow() -> None:
    """Lần 2 vẫn mã không có: máy này B6 không tra → luồng cũ (hỏi hành động bằng LLM, rồi dựng Action trên máy 404 → B12/B15
    quyết như trước); câu "không tìm thấy" chỉ gửi MỘT lần."""
    h, gw = _graph()
    await _submit(h, "Máy LAP-0012 của mình không vào được VPN")
    v = await _reply(h, "LAP-0013")
    assert v["status"] == S_CLARIFYING and v["missing_slots"] == ["action"]
    assert len(gw.llm.calls_for("b11_clarify_question")) == 1
    v = await _reply(h, "gia hạn giúp mình")
    assert v["intended_action"].params["device_id"] == "LAP-0013"
    assert _asked(h).count(NOT_FOUND) == 1 and len(_asked(h)) == 2
    assert not any(re.search(r"LAP-0013", t) for t in _asked(h))


EVIDENCE_D = "Máy LAP-0012 của mình không vào được VPN kiểm tra giúp"


@pytest.mark.asyncio
async def test_graph_evidence_d_with_action_hint_asks_code_then_continues() -> None:
    """Bằng chứng (d): B3 gợi ý sẵn `check_vpn_status` → đủ slot; trước: dựng Action trên LAP-0012 → E5 `llm_high_risk`.
    Nay: hỏi lại mã một lần; trả lời mã đúng → dựng Action trên máy đúng, giữ hành động người dùng đã nêu."""
    h, gw = _graph(action="check_vpn_status")
    v = await _submit(h, EVIDENCE_D)
    assert (v["status"], v.get("exit_code")) == (S_CLARIFYING, None)
    assert v.get("intended_action") is None and _asked(h) == [NOT_FOUND]
    v = await _reply(h, "LAP-0342")
    action = v["intended_action"]
    assert (action.type, action.params["device_id"]) == ("check_vpn_status", "LAP-0342")
    assert action.facts["device_owner_is_requester"] is True
    assert _asked(h) == [NOT_FOUND] and gw.llm.calls_for("b11_clarify_question") == []


@pytest.mark.asyncio
async def test_graph_full_slots_second_unknown_code_old_flow_asked_once() -> None:
    """Đủ slot, mã gửi lại vẫn không có: máy này B6 không tra (`device_lookup` None) → luồng cũ (dựng Action trên máy 404, B12/B15
    quyết) — câu "không tìm thấy" chỉ gửi MỘT lần."""
    h, _ = _graph(action="check_vpn_status")
    await _submit(h, EVIDENCE_D)
    v = await _reply(h, "LAP-0013")
    action = v["intended_action"]
    assert (action.params["device_id"], action.facts["device_registered"]) == ("LAP-0013", False)
    assert _asked(h) == [NOT_FOUND]
    assert v["status"] != S_CLARIFYING
