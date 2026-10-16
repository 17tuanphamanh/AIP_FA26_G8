"""Thay hợp đồng import-linter số 6 (01 mục 4.3, P1 mục 5.3, chốt 25/09/2026).

Node trong graph/nodes/** không được gọi thẳng hàm side effect. Tham chiếu tới chúng chỉ được
đứng ở tham số thứ ba của effects.once(state, kind, fn, ...). Import-linter không phân biệt được
"import để truyền vào once" với "gọi thẳng", nên kiểm bằng AST.

Giới hạn: bắt lời gọi qua tên/thuộc tính và mọi tham chiếu nằm ngoài vị trí `fn` (kể cả gán
biến rồi gọi). Không bắt getattr động hay hàm do module khác trả về.
"""

import ast
from pathlib import Path

import app.graph.nodes

# Thêm hàm side effect mới thì thêm tên vào đây (P1 mục 5.3).
SIDE_EFFECT_FUNCS = frozenset({
    "approvals.create",
    "approvals.notify_approver",
    "notify_user",
    "deadlines.set",
    "tickets.create_child",  # backend/app/db/tickets.py
    "tickets.deliver_round",  # parent_wait — qua effects.once("notify_user") cùng transaction đánh dấu notice (T20b P7)
    "escalations.create",  # B20 — qua effects.once("escalation_create") (D-18)
    "security_events.record",  # B2, clarify_wait, confirm_wait — qua effects.once("security_event") (3e, 8.2)
    "runner.submit",
})  # fmt: skip
ONCE = "effects.once"
FN_ARG_INDEX = 2  # once(state, kind, fn, ...)


def _matches(path: str, target: str) -> bool:
    return path == target or path.endswith("." + target)


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Tên cục bộ → đường dẫn đầy đủ, để `from app.db import tickets as t` vẫn ra `...tickets`."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    aliases[a.asname] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def _dotted(node: ast.expr, aliases: dict[str, str]) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(aliases.get(node.id, node.id))
    return ".".join(reversed(parts))


def find_violations(source: str, filename: str = "<node>") -> list[str]:
    tree = ast.parse(source, filename)
    aliases = _import_aliases(tree)

    allowed: set[int] = set()  # id() của nút nằm đúng vị trí `fn` trong effects.once
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _dotted(node.func, aliases)
            if callee and _matches(callee, ONCE) and len(node.args) > FN_ARG_INDEX:
                allowed.add(id(node.args[FN_ARG_INDEX]))

    violations: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name | ast.Attribute) or id(node) in allowed:
            continue
        path = _dotted(node, aliases)
        target = next((t for t in SIDE_EFFECT_FUNCS if path and _matches(path, t)), None)
        if target:
            violations.append((node.lineno, node.col_offset, target))
    # ast.walk duyệt theo chiều rộng — sắp lại theo vị trí trong file.
    return [f"{filename}:{line} {target}" for line, _, target in sorted(violations)]


def test_graph_nodes_never_call_side_effects_directly() -> None:
    nodes_dir = Path(app.graph.nodes.__file__).parent
    violations = [
        v
        for path in sorted(nodes_dir.rglob("*.py"))
        for v in find_violations(path.read_text(encoding="utf-8"), str(path.relative_to(nodes_dir)))
    ]
    assert violations == []


# ---- Mẫu giả: chứng minh checker bắt được lỗi khi graph/nodes còn rỗng ----------------------

GOOD_NODE = """
from app.approval import approvals
from app.graph import effects
from app.graph.effects import once
from app.notify.service import notify_user

async def b15(state):
    a_id = await effects.once(state, "approval_create", approvals.create, step="B15")
    await effects.once(state, "notify_approver", approvals.notify_approver, "u1", step="B15")
    await once(state, "notify_user", notify_user, state, "xin chao", step="B11")
    return a_id
"""

BAD_NODE = """
from app.approval import approvals
from app.db import tickets as t
from app.db.tickets import create_child as spawn
from app.graph import effects, runner
from app.notify.service import notify_user
import app.graph.deadlines as dl

async def bad(state):
    await approvals.create(ticket_id="t1")                                     # gọi thẳng
    await notify_user(state, "x")                                              # gọi thẳng
    await t.create_child("t1")                                                 # qua alias module
    await spawn("t1")                                                          # qua alias hàm
    await dl.set("t1", "clarify", hours=24)                                    # import ... as
    fn = runner.submit                                                         # gán rồi gọi
    await fn("t2")
    await effects.once(state, approvals.notify_approver, "k", step="B15")      # sai vị trí fn
"""


def test_checker_accepts_references_passed_to_once() -> None:
    assert find_violations(GOOD_NODE) == []


def test_checker_catches_direct_calls_in_fake_node() -> None:
    found = [v.split(" ", 1)[1] for v in find_violations(BAD_NODE)]
    assert found == [
        "approvals.create",
        "notify_user",
        "tickets.create_child",
        "tickets.create_child",
        "deadlines.set",
        "runner.submit",
        "approvals.notify_approver",
    ]


def test_checker_on_fake_file_in_nodes_layout(tmp_path: Path) -> None:
    # Cùng đường quét như test thật: rglob trên một thư mục có file node vi phạm.
    fake = tmp_path / "nodes" / "b99_fake.py"
    fake.parent.mkdir()
    fake.write_text(BAD_NODE, encoding="utf-8")
    hits = [v for p in fake.parent.rglob("*.py") for v in find_violations(p.read_text(), p.name)]
    assert hits and all(h.startswith("b99_fake.py:") for h in hits)
