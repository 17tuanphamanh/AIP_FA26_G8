"""Dựng graph (P1 mục 5): mỗi node = traced(with_error_boundary(fn)); cạnh = route_next theo ROUTES.

Checkpointer tiêm vào: `AsyncPostgresSaver` khi chạy thật (`checkpoint.open_postgres_saver`),
`InMemorySaver(serde=make_serde())` ở unit test. Node chưa có logic thật dùng bản GIẢ (`fake_nodes`).
"""

import functools
from collections.abc import Mapping
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.domain.ticket_state import TicketState
from app.graph.boundary import with_error_boundary
from app.graph.fakes import PAUSABLE_NODES, FakeScenario, NodeDeps
from app.graph.nodes import (
    approval_wait,
    b01_identity,
    b02_screen,
    b03_classify,
    b06_diagnose,
    b08_retrieve,
    b10_route,
    b11_slots,
    b12_assess,
    b15_prepare_approval,
    b17_execute,
    b20_audit,
    clarify_wait,
    confirm_wait,
    parent_reply_wait,
    parent_wait,
)
from app.graph.nodes.fake import b02_screen as fake_b02_screen
from app.graph.nodes.fake import b03_classify as fake_b03_classify
from app.graph.nodes.fake import b06_diagnose as fake_b06_diagnose
from app.graph.nodes.fake import b08_retrieve as fake_b08_retrieve
from app.graph.routing import ENTRY, ROUTES, route_next
from app.graph.tracing import NodeFn, traced

type Graph = CompiledStateGraph[Any, Any, Any, Any]

_NODE_MODULES = {
    "b01_identity": b01_identity, "b02_screen": fake_b02_screen, "b03_classify": fake_b03_classify,
    "b06_diagnose": fake_b06_diagnose, "b08_retrieve": fake_b08_retrieve, "b10_route": b10_route,
    "b11_slots": b11_slots, "clarify_wait": clarify_wait, "b12_assess": b12_assess,
    "b15_prepare_approval": b15_prepare_approval, "approval_wait": approval_wait,
    "b17_execute": b17_execute, "confirm_wait": confirm_wait, "parent_wait": parent_wait,
    "parent_reply_wait": parent_reply_wait, "b20_audit": b20_audit,
}  # fmt: skip

# Node THẬT đã có (thay dần _NODE_MODULES khi mỗi nhánh xong — 3-Q32 cách A). `real_nodes(deps)` dùng bảng
# này để ghi đè lên `fake_nodes(deps)`; node giả còn lại giữ nguyên tới khi có bản thật.
REAL_NODE_MODULES = {
    "b02_screen": b02_screen,  # 3e: L2 → L3 → L4 (phase3 mục 8.5)
    "b03_classify": b03_classify,  # 3f: VPN, đường LLM (phase3 mục 9.3)
    "b06_diagnose": b06_diagnose,  # 3f: 3 tool VPN song song + infer_vpn (phase3 mục 9.4, 9.5)
    "b08_retrieve": b08_retrieve,
}  # fmt: skip


def fake_nodes(deps: NodeDeps) -> dict[str, NodeFn]:
    """Toàn bộ node GIẢ (Phase 2). Phase sau thay từng mục bằng node thật. Node giả trong
    `PAUSABLE_NODES` có điểm dừng `scenario.pause` ở đầu node (FAKE_NODE_DELAY trên stack, 2b-4)."""
    nodes = {name: module.make(deps) for name, module in _NODE_MODULES.items()}
    for name in PAUSABLE_NODES:
        nodes[name] = _pausable(name, nodes[name], deps.scenario)
    return nodes


def real_nodes(deps: NodeDeps) -> dict[str, NodeFn]:
    """`fake_nodes(deps)` với các nhánh đã có bản thật (`REAL_NODE_MODULES`) ghi đè lên — node thật KHÔNG bọc
    `_pausable` (không đọc `deps.scenario`, 3-Q32 cách A)."""
    nodes = fake_nodes(deps)
    nodes.update({name: module.make(deps) for name, module in REAL_NODE_MODULES.items()})
    return nodes


def _pausable(name: str, fn: NodeFn, scenario: FakeScenario) -> NodeFn:
    @functools.wraps(fn)
    async def node(state: Any) -> dict[str, Any]:
        await scenario.pause(state, name)  # bên trong boundary: thẻ lạ ở đây cũng ra E9
        return await fn(state)

    return node


def wrap_node(name: str, fn: NodeFn) -> NodeFn:
    return traced(name, with_error_boundary(name, fn))


def build_graph(nodes: Mapping[str, NodeFn], checkpointer: BaseCheckpointSaver[Any]) -> Graph:
    if set(nodes) != set(ROUTES):
        raise ValueError(f"node lệch ROUTES: {sorted(set(nodes) ^ set(ROUTES))}")
    builder = StateGraph(TicketState)
    for name, fn in nodes.items():
        node: Any = wrap_node(name, fn)  # stub của LangGraph không nhận Callable chung
        builder.add_node(name, node)
    builder.add_edge(START, ENTRY)
    for name, targets in ROUTES.items():
        builder.add_conditional_edges(name, route_next, sorted(targets))
    return builder.compile(checkpointer=checkpointer)
