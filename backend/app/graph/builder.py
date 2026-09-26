"""Dựng graph (P1 mục 5): mỗi node = traced(with_error_boundary(fn)); cạnh = route_next theo ROUTES.

Checkpointer tiêm vào: `AsyncPostgresSaver` khi chạy thật (`checkpoint.open_postgres_saver`),
`InMemorySaver(serde=make_serde())` ở unit test. Node chưa có logic thật dùng bản GIẢ (`fake_nodes`).
"""

from collections.abc import Mapping
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.domain.ticket_state import TicketState
from app.graph.boundary import with_error_boundary
from app.graph.fakes import NodeDeps
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
from app.graph.routing import ENTRY, ROUTES, route_next
from app.graph.tracing import NodeFn, traced

type Graph = CompiledStateGraph[Any, Any, Any, Any]

_NODE_MODULES = {
    "b01_identity": b01_identity, "b02_screen": b02_screen, "b03_classify": b03_classify,
    "b06_diagnose": b06_diagnose, "b08_retrieve": b08_retrieve, "b10_route": b10_route,
    "b11_slots": b11_slots, "clarify_wait": clarify_wait, "b12_assess": b12_assess,
    "b15_prepare_approval": b15_prepare_approval, "approval_wait": approval_wait,
    "b17_execute": b17_execute, "confirm_wait": confirm_wait, "parent_wait": parent_wait,
    "parent_reply_wait": parent_reply_wait, "b20_audit": b20_audit,
}  # fmt: skip


def fake_nodes(deps: NodeDeps) -> dict[str, NodeFn]:
    """Toàn bộ node GIẢ (Phase 2). Phase sau thay từng mục bằng node thật."""
    return {name: module.make(deps) for name, module in _NODE_MODULES.items()}


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
