"""Q2 M2 (ĐP 09/11) — mọi câu trả lời B10 ngắn, từng bước: tối đa 3 bước (code cắt nếu LLM trả nhiều hơn, audit
`steps_truncated`), câu kết CỐ ĐỊNH (code) sau các bước, trước mục nguồn; `b10_answer` v3 (xưng "mình", gọi "bạn").
Nhãn nút trong câu kết khớp FE (`ChatPage.tsx`: "Đã ổn"/"Chưa ổn"; `messages.CONFIRMED_TEXT`/`UNRESOLVED_TEXT`).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.domain.answer import MAX_ANSWER_STEPS, cap_steps, render_answer
from app.domain.context import RequesterContext
from app.domain.messages import ANSWER_CLOSING, CONFIRMED_TEXT, UNRESOLVED_TEXT
from app.domain.states import S_CONFIRMING, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b10_route
from app.llm.providers.scripted import Reply
from app.llm.registry import load_prompts
from app.rag.models import EvidenceBlock
from tests.fakes.graph import GraphHarness
from tests.fakes.kb_index import KBV
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag

CONFIG = Path(__file__).resolve().parents[3] / "config"
CLOSING = ("Bạn thử lần lượt rồi báo mình nhé: chọn \"Đã ổn\" nếu đã được, \"Chưa ổn\" nếu vẫn lỗi để mình chuyển kỹ thuật "
           "viên kèm thông tin đã kiểm tra.")  # fmt: skip
SIX = [f"Bước số {i}" for i in range(1, 7)]
REF = ChunkRef(chunk_id="KB-VPN-003#v1#2", doc_id="KB-VPN-003", version=1, seq=2, title="Lỗi 809", heading_path="Mục 2",
               score=0.9, excerpt="x")  # fmt: skip


def test_closing_text_fixed_and_matches_fe_buttons() -> None:
    assert ANSWER_CLOSING == CLOSING
    assert f'"{CONFIRMED_TEXT}"' in ANSWER_CLOSING and f'"{UNRESOLVED_TEXT}"' in ANSWER_CLOSING
    fe = (Path(__file__).resolve().parents[3] / "frontend/src/routes/employee/ChatPage.tsx").read_text(encoding="utf-8")
    assert CONFIRMED_TEXT in fe and UNRESOLVED_TEXT in fe  # nút xác nhận của tin một ý


@pytest.mark.parametrize(("steps", "kept", "truncated"), [
    (SIX, SIX[:3], True),
    (SIX[:3], SIX[:3], False),
    (["a", "  ", "b", "", "c"], ["a", "b", "c"], False),  # bước rỗng không tính
    (["a", "b", "c", "d"], ["a", "b", "c"], True),
    (None, [], False),
    ([], [], False),
])  # fmt: skip
def test_cap_steps(steps: list[str] | None, kept: list[str], truncated: bool) -> None:
    assert MAX_ANSWER_STEPS == 3
    assert cap_steps(steps) == (kept, truncated)


def test_render_closing_after_steps_before_sources() -> None:
    body = render_answer("Bạn làm như sau.", ["Mở ABC Connect", "Chọn SSTP"], [REF])
    assert body == (
        f"Bạn làm như sau.\n\n1. Mở ABC Connect\n2. Chọn SSTP\n\n{CLOSING}\n\nNguồn:\n- Lỗi 809 › Mục 2"
    )


def test_render_no_steps_no_closing() -> None:
    assert render_answer("VPN dùng cổng 443.", None, [REF]) == "VPN dùng cổng 443.\n\nNguồn:\n- Lỗi 809 › Mục 2"


# ---- node: LLM trả 6 bước → gửi 3 bước + câu kết, audit steps_truncated -----------------------------------------------


def _ctx() -> RequesterContext:
    return RequesterContext(
        user_id="nv-fake", role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _env(steps: list[str] | None) -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    answer = Reply({"answer_markdown": "Lỗi 809 thường do mạng chặn cổng.", "citations": [REF.chunk_id], "steps": steps,
                    "cannot_answer": False})  # fmt: skip
    gw = make_gateway({"b10_need_type": [Reply({"type": "info", "confidence": 0.9})], "b10_answer": [answer]},
                      clock=clock)  # fmt: skip
    block = EvidenceBlock(anchor_chunk_id=REF.chunk_id, doc_id=REF.doc_id, title=REF.title,
                          heading_path=REF.heading_path, score=REF.score, text="nội dung", tokens=50)  # fmt: skip
    return GraphHarness(clock=clock, llm=gw.client, rag=FakeRag(evidence=[block])), gw


@contextmanager
def _run(h: GraphHarness) -> Iterator[None]:
    with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=h.audit, effects=h.effects, spans=h.spans,
                             clock=h.clock, txlog=h.txlog)):  # fmt: skip
        yield


class _SpyGuard:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def violation(self, text: str) -> str | None:
        self.seen.append(text)
        return None


async def _node(h: GraphHarness, **deps_over: Any) -> dict[str, Any]:
    deps = h.deps()
    for k, v in deps_over.items():
        setattr(deps, k, v)
    state = {"ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": "VPN báo lỗi 809",
             "intent": "vpn", "retrieved": [REF], "retrieval_score": 0.9, "kb_version": KBV, "requester_context": _ctx(),
             "slots": {}, "facts": {}}  # fmt: skip
    with _run(h):
        return await b10_route.make(deps)(state)


def _detail(h: GraphHarness) -> dict[str, Any]:
    [row] = [r for r in h.audit.rows if r["step"] == "B10"]
    return dict(row["detail"])


@pytest.mark.asyncio
async def test_six_steps_truncated_to_three_with_closing() -> None:
    h, _ = _env(SIX)
    spy = _SpyGuard()
    out = await _node(h, output_guard=spy)
    assert out["status"] == S_CONFIRMING
    [(_, text, _)] = h.notifier.sent
    assert "3. Bước số 3" in text and "Bước số 4" not in text and "4. " not in text
    assert text.index("3. Bước số 3") < text.index(CLOSING) < text.index("Nguồn:")
    assert _detail(h)["steps_truncated"] is True
    assert spy.seen == [text]  # output guard chạy trên TOÀN tin (kể cả câu kết)


@pytest.mark.asyncio
async def test_three_steps_not_truncated() -> None:
    h, _ = _env(SIX[:3])
    await _node(h)
    [(_, text, _)] = h.notifier.sent
    assert "3. Bước số 3" in text and CLOSING in text
    assert _detail(h)["steps_truncated"] is False


# ---- b10_answer v3 ---------------------------------------------------------------------------------------------------------


def test_b10_answer_prompt_v3_short_steps_and_voice() -> None:
    prompt = {p.id: p for p in load_prompts(CONFIG / "prompts")}["b10_answer"]
    assert prompt.spec.version == 3
    system = prompt.spec.system
    assert "TỐI ĐA 3 bước" in system and "cao nhất" in system
    assert '"mình"' in system and '"bạn"' in system
    for banned in ("chúng tôi", "anh/chị", "quý khách"):
        assert banned in system  # nêu đích danh để cấm
    assert "tối đa 8 bước" not in system
    raw = (CONFIG / "prompts" / "b10_answer.yaml").read_text(encoding="utf-8")
    assert raw.index("# v3") < raw.index("id: b10_answer")  # lý do tăng version ghi đầu file
