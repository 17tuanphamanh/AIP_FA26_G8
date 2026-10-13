"""Hàm dùng chung cho test T20b (phase5 5.2.8) — không phải file test (tên bắt đầu `_`, pytest không gom).

- `Flow`: graph THẬT (`GraphHarness(nodes="real")`) + `InMemorySaver` + ScriptedLLM qua gateway THẬT (`tests/fakes/llm.make_gateway`)
  + registry đọc thật trên seed (`tests/unit/_t20a.Env`) + store giả (`tests/fakes/graph.py`). `enabled_intents` tiêm bằng lớp con
  `IntentsHarness` (ghi đè `deps()` bằng `dataclasses.replace` — KHÔNG sửa `graph/fakes.py`/`tests/fakes`), mặc định 4 intent.
- Kịch bản LLM dùng chung mọi ticket (cha + con): `b02_injection_judge` không tấn công, `b03_classify` MỘT phản hồi (chỉ cha gọi —
  con gọi thêm thì `ScriptExhausted` → E9, thấy được), `b10_need_type` = action, `b11_clarify_question` câu hỏi cố định,
  `b11_extract_slots` theo `extract`.
- Câu kịch bản lấy theo bảng 5.2.7 (tc34, tc35, tc32 …); người gửi nv001 (seed: LAP-0342, finance).
"""

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from app.domain.ticket_state import ChunkRef
from app.graph.fakes import NodeDeps
from app.graph.late_event import deliver_event
from app.graph.runner import RunResult
from app.llm.providers.scripted import Reply, Step
from app.rag.models import RetrievalResult
from tests.fakes.graph import GraphHarness
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag
from tests.unit._t20a import Env

FOUR =frozenset({"vpn", "account", "software", "access"})
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ bình thường"}
QUESTION = "Bạn cần gia hạn thêm bao nhiêu ngày?"
SESSION_NV001 = "s-nv001"
PARENT = "T1"

# bảng 5.2.7 — câu + span
RESET = "đặt lại mật khẩu tài khoản AD"
ADOBE = "cài luôn Adobe Acrobat Pro"
TC34 = f"{RESET} giúp mình, tiện {ADOBE}"
EXTEND = "gia hạn quyền thư mục finance/public-reports"
TC35 = f"{RESET} và {EXTEND}"
PRINTER = "sửa máy in tầng 3 giúp mình"
TC32 = f"{RESET}, tiện {PRINTER}"


def item(
    type_: str, span: str, *, confidence: float = 0.92, action: str | None = None, slots: Mapping[str, str] | None = None
) -> dict[str, Any]:
    return {"type": type_, "confidence": confidence, "span": span, "action_hint": action, "slots": dict(slots or {})}


def reset_item(span: str = RESET, **kw: Any) -> dict[str, Any]:
    return item("account", span, action="reset_password", slots={"account_type": "ad"}, **kw)


def adobe_item(span: str = ADOBE, **kw: Any) -> dict[str, Any]:
    return item("software", span, action="install_software", slots={"software_name": "Adobe Acrobat Pro"}, **kw)


def extend_item(span: str = EXTEND, **kw: Any) -> dict[str, Any]:
    return item("access", span, action="extend_permission", slots={"resource_path": "finance/public-reports"}, **kw)


def oos_item(span: str = PRINTER, **kw: Any) -> dict[str, Any]:
    return item("out_of_scope", span, **kw)


def classify(*items: dict[str, Any]) -> Reply:
    return Reply({"intents": list(items), "is_multi": len(items) >= 2})


def rag() -> FakeRag:
    chunk = ChunkRef(chunk_id="c1", doc_id="KB-ACC-001", version=1, seq=0, title="T", heading_path="H",
                     score=0.99, excerpt="x")  # fmt: skip
    return FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.99, kb_version="a" * 64,
                                          intent_filter_fallback=False, fallback_tried=False, retries=0,
                                          query_truncated=False))  # fmt: skip


class IntentsHarness(GraphHarness):
    """`GraphHarness` với `enabled_intents` tiêm vào MỌI `deps()` (mỗi process/restart) — không sửa `tests/fakes`."""

    intents: frozenset[str] = FOUR

    def deps(self) -> NodeDeps:
        return dataclasses.replace(super().deps(), enabled_intents=self.intents)


@dataclasses.dataclass
class Flow:
    h: IntentsHarness
    gw: Gateway
    env: Env

    @property
    def parent(self) -> str:
        return PARENT

    def child(self, i: int) -> str:
        return f"{PARENT}-{i}"

    async def submit(self, text: str) -> RunResult:
        """Như API: dòng `tickets` của cha (người gửi nv001 — chủ ticket khi gọi qua HTTP) có trước, rồi submit graph."""
        self.h.tickets.register(PARENT, self.h.clock.now(), requester_id="nv001", session_id=SESSION_NV001,
                                redacted_request=text, requester_dept="finance")  # fmt: skip
        return await self.h.submit_as(PARENT, SESSION_NV001, text=text)

    async def values(self, ticket_id: str) -> dict[str, Any]:
        return dict((await self.h.runner.snapshot(ticket_id)).values)

    async def waiting(self, ticket_id: str) -> str | None:
        snap = await self.h.runner.snapshot(ticket_id)
        return snap.next[0] if snap.next else None

    async def deliver(self, ticket_id: str, status: str, event: Mapping[str, Any], **kw: Any) -> RunResult:
        return await deliver_event(self.h.runner, ticket_id, status, event, **kw)

    async def assistant_msgs(self, ticket_id: str = PARENT) -> list[dict[str, Any]]:
        return [m for m in (await self.values(ticket_id)).get("conversation") or [] if m.get("role") == "assistant"]

    async def user_msgs(self, ticket_id: str = PARENT) -> list[dict[str, Any]]:
        return [m for m in (await self.values(ticket_id)).get("conversation") or [] if m.get("role") == "user"]

    def b03_calls(self) -> int:
        return len(self.gw.llm.calls_for("b03_classify"))

    def approval_of(self, ticket_id: str) -> str:
        ids = [a for a, row in self.h.approvals._table.items() if row["ticket_id"] == ticket_id]
        assert len(ids) == 1, (ticket_id, ids)  # AssertionError (không ValueError) — ca DỪNG 2 xfail(strict) bắt đúng loại
        return ids[0]

    def decision(self, ticket_id: str, kind: str = "approved", note: str | None = None) -> dict[str, Any]:
        """Sự kiện B16 như route duyệt dựng (người duyệt = người được giao trên phiếu)."""
        row = self.h.approvals._table[self.approval_of(ticket_id)]
        event: dict[str, Any] = {"kind": kind, "approver_id": row["approver_id"], "decided_as": "l1",
                                 "at": self.h.clock.now().isoformat()}  # fmt: skip
        if note is not None:
            event["note"] = note
        return event


def make_flow(
    b03: Reply | Sequence[Reply] | None = None,
    *,
    intents: frozenset[str] = FOUR,
    extract: Callable[[Mapping[str, Any]], Mapping[str, str]] | Mapping[str, str] | None = None,
    need_type: str = "action",
    **harness: Any,
) -> Flow:
    env = Env()
    replies: list[Step] = [b03] if isinstance(b03, Reply) else list(b03 or [])
    fixed: Mapping[str, str] = {} if callable(extract) or extract is None else dict(extract)

    def extracted(variables: Mapping[str, Any]) -> Mapping[str, str]:
        return extract(variables) if callable(extract) else fixed

    gw = make_gateway({
        "b02_injection_judge": lambda _: Reply(NOT_ATTACK),
        "b03_classify": replies,
        "b10_need_type": lambda _: Reply({"type": need_type, "confidence": 0.9}),
        "b11_clarify_question": lambda _: Reply({"text": QUESTION}),
        "b11_extract_slots": lambda v: Reply({"slots": dict(extracted(v)), "off_topic": False}),
    }, clock=env.clock)  # fmt: skip
    h =IntentsHarness(clock=env.clock, nodes="real", llm=gw.client, rag=rag(), directory=env.directory(), **harness)
    if intents != FOUR:
        h.intents = intents
        h.restart()
    h.identity.add_session(SESSION_NV001, "nv001", expires_at=env.clock.now() + timedelta(days=365))
    return Flow(h, gw, env)
