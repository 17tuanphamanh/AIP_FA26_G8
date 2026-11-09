"""Q2 M1 (ĐP 09/11) — B10 "báo lỗi VPN khi chứng chỉ còn hạn": need_type `action` nhưng chưa có slot `action`, fact B6 cho thấy
máy CỦA người gửi, đã đăng ký, chứng chỉ còn hạn → đi nhánh info (B9 → expand → b10_answer), KHÔNG xuống B11 hỏi
"cấp mới, gia hạn hay thu hồi". Câu mở đầu theo fact do CODE ghép (không LLM). Ca khác giữ nguyên (`needs_action` → B11).

Bằng chứng (a): chau.hm (nv003, LAP-0501, cert còn 5 ngày) gõ "VPN của mình không kết nối được báo lỗi 809" → bot hỏi hành động.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.messages import symptom_intro
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b10_route
from app.llm.providers.scripted import Reply, Script
from app.rag.models import EvidenceBlock
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user
from tests.fakes.kb_index import KBV, fixture_rag
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts

QUESTION = "VPN của mình không kết nối được báo lỗi 809"
INTRO = "Mình đã kiểm tra máy LAP-0501: máy đã đăng ký, chứng chỉ VPN còn hạn 5 ngày, nên lỗi không nằm ở chứng chỉ."
LAST_FAIL = "Lần kết nối gần nhất không thành công."
CHAU: dict[str, Any] = {
    "device_count": 1, "has_registered_device": True, "device_registered": True, "device_owner_is_requester": True,
    "cert_status": "valid", "cert_days_to_expiry": 5,
}  # fmt: skip


def _ctx(user: str = "nv003") -> RequesterContext:
    return RequesterContext(
        user_id=user, role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _ref(doc: str, seq: int, score: float, title: str) -> ChunkRef:
    return ChunkRef(chunk_id=f"{doc}#v1#{seq}", doc_id=doc, version=1, seq=seq, title=title,
                    heading_path=f"Mục {seq}", score=score, excerpt="x")  # fmt: skip


TOP = [_ref("KB-VPN-003", 2, 0.9, "Lỗi 809"), _ref("KB-VPN-001", 1, 0.8, "VPN công ty")]


def _block(c: ChunkRef) -> EvidenceBlock:
    return EvidenceBlock(anchor_chunk_id=c.chunk_id, doc_id=c.doc_id, title=c.title, heading_path=c.heading_path,
                         score=c.score, text="nội dung", tokens=50)  # fmt: skip


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": QUESTION, "intent": "vpn",
        "retrieved": list(TOP), "retrieval_score": TOP[0].score, "kb_version": KBV, "requester_context": _ctx(),
        "slots": {"device_id": "LAP-0501"}, "facts": dict(CHAU),
    }  # fmt: skip
    base.update(over)
    return base


def _answer(_: Any) -> Reply:
    return Reply({"answer_markdown": "Lỗi 809 thường do mạng chặn cổng VPN.", "citations": [TOP[0].chunk_id],
                  "steps": ["Tắt Wi-Fi điện thoại", "Chọn SSTP"], "cannot_answer": False})  # fmt: skip


def _env(*, need: str = "action", answer: Script = _answer) -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    gw = make_gateway({"b10_need_type": lambda _: Reply({"type": need, "confidence": 0.9}), "b10_answer": answer},
                      clock=clock)  # fmt: skip
    return GraphHarness(clock=clock, llm=gw.client, rag=FakeRag(evidence=[_block(c) for c in TOP])), gw


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
        return await b10_route.make(deps)(state)


def _row(h: GraphHarness) -> dict[str, Any]:
    [row] = [r for r in h.audit.rows if r["step"] in ("B10", "B9")]
    return row


# ---- câu mở đầu theo fact (hàm thuần, không LLM) ---------------------------------------------------------------------


@pytest.mark.parametrize(("device", "facts", "expected"), [
    ("LAP-0501", CHAU, INTRO),
    ("LAP-0501", {**CHAU, "last_connection_ok": False}, f"{INTRO} {LAST_FAIL}"),
    ("LAP-0501", {**CHAU, "last_connection_ok": True}, INTRO),
    ("LAP-0501", {k: v for k, v in CHAU.items() if k != "cert_days_to_expiry"},
     "Mình đã kiểm tra máy LAP-0501: máy đã đăng ký, chứng chỉ VPN còn hạn, nên lỗi không nằm ở chứng chỉ."),
    ("LAP-0501", {**CHAU, "cert_days_to_expiry": True},  # bool không phải số ngày
     "Mình đã kiểm tra máy LAP-0501: máy đã đăng ký, chứng chỉ VPN còn hạn, nên lỗi không nằm ở chứng chỉ."),
    ("lap 0501; DROP", CHAU,  # mã sai mẫu không in ra
     "Mình đã kiểm tra máy của bạn: máy đã đăng ký, chứng chỉ VPN còn hạn 5 ngày, nên lỗi không nằm ở chứng chỉ."),
    (None, CHAU, "Mình đã kiểm tra máy của bạn: máy đã đăng ký, chứng chỉ VPN còn hạn 5 ngày, nên lỗi không nằm ở chứng chỉ."),
])  # fmt: skip
def test_symptom_intro_from_facts_only(device: str | None, facts: dict[str, Any], expected: str) -> None:
    assert symptom_intro(device, facts) == expected


# ---- node: ca Châu → nhánh info, 0 câu hỏi B11 -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_cert_symptom_answers_from_kb_not_b11() -> None:
    h, gw = _env()
    out = await _node(h, _state())
    assert (out["status"], out["next"], out["need_type"]) == (S_CONFIRMING, "confirm_wait", "info")
    assert [c.prompt_id for c in gw.llm.calls] == ["b10_need_type", "b10_answer"]
    [(_, text, needs)] = h.notifier.sent
    assert needs == "confirm" and text.startswith(INTRO + "\n\n")
    assert LAST_FAIL not in text  # không có fact kết nối → không thêm vế
    assert "1. Tắt Wi-Fi điện thoại" in text and "Nguồn:\n- Lỗi 809 › Mục 2" in text
    [msg] = out["conversation"]
    assert msg["kind"] == "answer" and msg["text"] == text
    row = _row(h)
    assert (row["event"], row["detail"]["symptom_to_info"], row["detail"]["need_type"]) == (
        "deflected_info_only", True, "action",
    )  # fmt: skip
    assert INTRO not in repr(h.audit.rows)  # audit không mang chữ gửi người dùng


@pytest.mark.asyncio
async def test_last_connection_failed_adds_sentence() -> None:
    h, _ = _env()
    await _node(h, _state(facts={**CHAU, "last_connection_ok": False}))
    [(_, text, _)] = h.notifier.sent
    assert text.startswith(f"{INTRO} {LAST_FAIL}\n\n")


@pytest.mark.parametrize(("why", "over"), [
    ("cert-het-han", {"facts": {**CHAU, "cert_status": "expired", "cert_days_to_expiry": -4}}),
    ("cert-thu-hoi", {"facts": {**CHAU, "cert_status": "revoked"}}),
    ("may-nguoi-khac", {"facts": {**CHAU, "device_owner_is_requester": False}}),
    ("chua-dang-ky", {"facts": {**CHAU, "device_registered": False}}),
    ("da-co-action", {"slots": {"device_id": "LAP-0501", "action": "check_vpn_status"}}),
    ("khong-co-fact-may", {"facts": {"device_count": 2, "has_registered_device": True}, "slots": {}}),
    ("tat-chan-doan", {"facts": {}}),
    ("intent-khac", {"intent": "software"}),
])  # fmt: skip
@pytest.mark.asyncio
async def test_other_action_cases_unchanged_go_to_b11(why: str, over: dict[str, Any]) -> None:
    h, gw = _env()
    out = await _node(h, _state(**over))
    assert (out["status"], out["next"], out["need_type"]) == (S_RETRIEVING, "b11_slots", "action"), why
    assert gw.llm.calls_for("b10_answer") == [] and h.notifier.sent == []
    row = _row(h)
    assert (row["event"], row["detail"]["symptom_to_info"]) == ("needs_action", False)


@pytest.mark.asyncio
async def test_info_need_type_not_marked_symptom_no_intro() -> None:
    h, _ = _env(need="info")
    out = await _node(h, _state())
    assert out["status"] == S_CONFIRMING
    [(_, text, _)] = h.notifier.sent
    assert "Mình đã kiểm tra máy" not in text
    assert _row(h)["detail"]["symptom_to_info"] is False


@pytest.mark.asyncio
async def test_symptom_without_grounding_is_e3_b9() -> None:
    """Giữ cổng grounding: điểm truy hồi dưới ngưỡng → E3 `no_grounding` ở B9 như nhánh info, 0 expand, 0 b10_answer."""
    h, gw = _env()
    out = await _node(h, _state(retrieval_score=0.1))
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E3", "no_grounding")
    row = _row(h)
    assert (row["step"], row["event"], row["detail"]["symptom_to_info"]) == ("B9", "no_evidence", True)
    assert gw.llm.calls_for("b10_answer") == [] and h.rag.expand_calls == [] and h.notifier.sent == []


@pytest.mark.asyncio
async def test_symptom_cannot_answer_is_e3() -> None:
    h, _ = _env(answer=lambda _: Reply({"answer_markdown": "", "citations": [], "cannot_answer": True}))
    out = await _node(h, _state())
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "no_grounding")
    assert h.notifier.sent == []


class _SpyGuard:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def violation(self, text: str) -> str | None:
        self.seen.append(text)
        return "secret" if "LAP-0501" in text else None


@pytest.mark.asyncio
async def test_output_guard_sees_whole_message_with_intro() -> None:
    """Output guard chạy trên TOÀN tin (câu fact + câu trả lời) — chặn thì 0 tin gửi đi."""
    h, _ = _env()
    spy = _SpyGuard()
    out = await _node(h, _state(), output_guard=spy)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "output_guard_block")
    [seen] = spy.seen
    assert seen.startswith(INTRO) and "Tắt Wi-Fi điện thoại" in seen
    assert h.notifier.sent == []


# ---- graph thật B1 → … → B6 → B8 → B10: nv003 (LAP-0501 còn hạn) và nv001 (LAP-0342 hết hạn) -------------------------


async def _graph(user: str) -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    gw = make_gateway(vpn_scripts(need="action", action=None), clock=clock)  # type: ignore[arg-type]
    rag = await fixture_rag(["KB-VPN-003#v1#2", "KB-VPN-001#v1#1"], clock)
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=rag, ad=FakeAd(ad_user(user)))  # type: ignore[arg-type]
    h.identity.add_session(f"s-{user}", user, expires_at=clock.now() + timedelta(days=365))
    h.tickets.register("t1", clock.now(), requester_id=user)
    return h, gw


@pytest.mark.asyncio
async def test_graph_chau_valid_cert_error_809_answered_no_question() -> None:
    h, gw = await _graph("nv003")
    v = (await h.runner.submit("t1", session_id="s-nv003",
                               redacted_request="VPN máy LAP-0501 của mình không kết nối được báo lỗi 809")).values  # fmt: skip
    assert (v["status"], v["need_type"]) == (S_CONFIRMING, "info")
    assert gw.llm.calls_for("b11_clarify_question") == [] and v.get("intended_action") is None
    [msg] = [m for m in v["conversation"] if m.get("kind") == "answer"]
    assert msg["text"].startswith("Mình đã kiểm tra máy LAP-0501: máy đã đăng ký, chứng chỉ VPN còn hạn ")
    assert "nên lỗi không nằm ở chứng chỉ." in msg["text"]
    assert any(s["chunk_id"].startswith("KB-VPN-003#") for s in msg["sources"])
    [row] = h.audit.of("t1", "deflected_info_only")
    assert row["detail"]["symptom_to_info"] is True


@pytest.mark.asyncio
async def test_graph_expired_cert_still_goes_renew() -> None:
    """Cert hết hạn (nv001, LAP-0342) → `infer_vpn` đặt action renew như cũ → B11 dựng Action, không trả lời KB."""
    h, gw = await _graph("nv001")
    v = (await h.runner.submit("t1", session_id="s-nv001",
                               redacted_request="VPN máy LAP-0342 của mình không kết nối được")).values  # fmt: skip
    assert gw.llm.calls_for("b10_answer") == []
    assert v["need_type"] == "action" and v["intended_action"].type == "renew_vpn_cert"
    [row] = h.audit.of("t1", "needs_action")
    assert row["detail"]["symptom_to_info"] is False
