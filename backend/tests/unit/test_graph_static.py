"""Kiểm tĩnh graph — P1 mục 5, 5.1.1 (D-29), mục 11 dòng 3 + "Mọi goto trong graph/nodes/ qua
is_allowed"; cổng 2 "mọi trạng thái ra của mỗi node có đích định tuyến".

Quét AST mọi `goto(state, S_X, next_node=…)` trong graph/nodes/: đích phải thuộc ROUTES của node; trạng
thái vào của node suy từ các goto khác trỏ tới nó; mọi cặp (vào → ra) phải qua `is_allowed`.
"""

import ast
from collections import defaultdict
from pathlib import Path

import app.graph.nodes
import pytest
from app.domain import states
from app.domain.states import S_NEW, forbidden_rule, is_allowed
from app.graph.routing import AUDIT, ENTRY, ROUTES, WAIT_NODES
from langgraph.graph import END
from tests.fakes.graph import GraphHarness

NODES_DIR = Path(app.graph.nodes.__file__).parent
PARENT_NODES = {"parent_wait", "parent_reply_wait"}  # quy tắc 3 (D-31): chỉ ticket cha
D20 = (states.S_CLARIFYING, states.S_DIAGNOSING)


def _const_targets(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _const_targets(node.body) | _const_targets(node.orelse)
    raise AssertionError(f"next_node phải là hằng chuỗi (dòng {node.lineno})")


def collect_gotos() -> dict[str, list[tuple[str, set[str], str, str]]]:
    """node → [(to_status, next_nodes, step, event)] cho mọi lời gọi goto trong graph/nodes/."""
    found: dict[str, list[tuple[str, set[str], str, str]]] = defaultdict(list)
    for path in sorted(NODES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef) or fn.name not in ROUTES:
                continue
            for call in ast.walk(fn):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                        and call.func.id == "goto"):  # fmt: skip
                    continue
                to = call.args[1]
                assert isinstance(to, ast.Name) and to.id.startswith("S_"), f"{path.name}:{call.lineno}"
                kw = {k.arg: k.value for k in call.keywords}
                event = kw["event"]
                event_s = event.value if isinstance(event, ast.Constant) else "<expr>"
                step = kw["step"]
                assert isinstance(step, ast.Constant)
                found[fn.name].append(
                    (getattr(states, to.id), _const_targets(kw["next_node"]), step.value, event_s)
                )
    return found


GOTOS = collect_gotos()


def entry_states() -> dict[str, set[str]]:
    entries: dict[str, set[str]] = defaultdict(set)
    entries[ENTRY].add(S_NEW)
    for calls in GOTOS.values():
        for to, targets, _, _ in calls:
            for t in targets:
                entries[t].add(to)
    return entries


def test_every_node_except_audit_has_gotos() -> None:
    assert set(GOTOS) == set(ROUTES) - {AUDIT}


def test_every_goto_target_is_in_routes_of_its_node() -> None:
    for node, calls in GOTOS.items():
        for _, targets, _, _ in calls:
            assert targets <= ROUTES[node], (node, targets - ROUTES[node])


def test_every_entry_to_exit_pair_passes_is_allowed() -> None:
    entries = entry_states()
    needs_flag: set[tuple[str, str]] = set()
    for node, calls in GOTOS.items():
        assert entries[node], f"{node} không có đường vào"
        view = {"is_parent": node in PARENT_NODES}
        for frm in entries[node]:
            for to, _, step, event in calls:
                assert forbidden_rule(view, frm, to, step=step, event=event) is None or (
                    frm, to) in {(states.S_PENDING_APPROVAL, states.S_EXECUTING)}, (node, frm, to)
                if is_allowed(view, frm, to):
                    continue
                assert is_allowed(view, frm, to, rediagnose_on_new_slot=True), (node, frm, to)
                needs_flag.add((frm, to))
    assert needs_flag <= {D20}  # chỉ đích D-20 cần cờ REDIAGNOSE_ON_NEW_SLOT


def test_every_node_reaches_audit_and_is_reachable_from_entry() -> None:
    assert all(AUDIT in targets for name, targets in ROUTES.items() if name != AUDIT)
    assert ROUTES[AUDIT] == {END}
    seen, todo = {ENTRY}, [ENTRY]
    while todo:
        for nxt in ROUTES.get(todo.pop(), ()):
            if nxt != END and nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    assert seen == set(ROUTES)


def test_wait_nodes_are_routed_nodes() -> None:
    assert set(WAIT_NODES) <= set(ROUTES)


@pytest.mark.parametrize("name", sorted(ROUTES))
def test_every_compiled_node_is_traced_then_boundary(name: str) -> None:
    graph = GraphHarness().runner.graph
    outer = graph.builder.nodes[name].runnable.afunc  # type: ignore[attr-defined]
    assert outer.__dict__.get("traced"), name  # traced(...) ngoài cùng
    inner = outer.__wrapped__
    assert inner.__dict__.get("error_boundary") and not inner.__dict__.get("traced"), name
    assert inner.__wrapped__.__name__ == name
