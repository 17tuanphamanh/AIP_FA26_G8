"""c33 (3c, Q-3c-14) — hai kiểm AST tĩnh, không chạy graph thật:

1. Mọi tham số từ khoá của lời gọi `goto(...)` trong `graph/nodes/**` (trừ 5 tham số riêng của chữ ký
   `goto` — `next_node`, `step`, `event`, `audit_detail`, `lineage` (3g) — vốn KHÔNG vào `**fields`/state) phải thuộc
   `TicketState.STATE_KEYS`. `goto()` tự kiểm điều này lúc chạy (`check_state_keys`); bài test này bắt
   sớm lúc review/CI, không cần dựng RunContext.
2. Mọi chuỗi gán cho tham số `escalation_reason_detail` trong toàn bộ `graph/**` (kể cả qua hằng số
   module-level như `RECOVER_EXHAUSTED` ở `runner.py`) phải thuộc `domain.exit_codes.REASON_DETAILS`.
"""

import ast
from pathlib import Path

import app.graph
import app.graph.nodes
from app.domain.exit_codes import REASON_DETAILS
from app.domain.ticket_state import STATE_KEYS

# Tham số riêng của chữ ký `goto()` — không đi vào `**fields` nên không phải state key.
GOTO_OWN_PARAMS = frozenset({"next_node", "step", "event", "audit_detail", "lineage"})


def _module_str_constants(tree: ast.Module) -> dict[str, str]:
    """`NAME = "literal"` ở top-level module — để giải `escalation_reason_detail=HANG_SO`."""
    out: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            out[node.targets[0].id] = node.value.value
    return out


def _goto_fields_keywords(tree: ast.AST, filename: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "goto":
            for kw in node.keywords:
                if kw.arg is None or kw.arg in GOTO_OWN_PARAMS:
                    continue
                found.append(f"{filename}:{node.lineno} {kw.arg}")
    return found


def _reason_detail_values(tree: ast.Module, filename: str) -> list[tuple[str, str]]:
    consts = _module_str_constants(tree)
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "escalation_reason_detail":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                out.append((f"{filename}:{node.lineno}", kw.value.value))
            elif isinstance(kw.value, ast.Name) and kw.value.id in consts:
                out.append((f"{filename}:{node.lineno}", consts[kw.value.id]))
            else:
                out.append((f"{filename}:{node.lineno}", f"<khong-giai-duoc:{ast.dump(kw.value)}>"))
    return out


def test_goto_keyword_fields_are_known_state_keys() -> None:
    nodes_dir = Path(app.graph.nodes.__file__).parent
    all_hits: list[str] = []
    seen_keys: set[str] = set()
    for path in sorted(nodes_dir.rglob("*.py")):
        rel = str(path.relative_to(nodes_dir))
        tree = ast.parse(path.read_text(encoding="utf-8"), rel)
        for hit in _goto_fields_keywords(tree, rel):
            key = hit.split(" ", 1)[1]
            seen_keys.add(key)
            if key not in STATE_KEYS:
                all_hits.append(hit)
    assert all_hits == []
    assert len(seen_keys) >= 20, f"tập quét chỉ có {len(seen_keys)} key — nghi ngờ quét rỗng"


def test_escalation_reason_detail_strings_are_known() -> None:
    graph_dir = Path(app.graph.__file__).parent
    bad: list[str] = []
    for path in sorted(graph_dir.rglob("*.py")):
        rel = str(path.relative_to(graph_dir))
        tree = ast.parse(path.read_text(encoding="utf-8"), rel)
        for loc, value in _reason_detail_values(tree, rel):
            if value not in REASON_DETAILS:
                bad.append(f"{loc} {value!r}")
    assert bad == []


# ---- Mẫu giả: chứng minh checker bắt được lỗi (giống khuôn test_side_effects_ast.py) -----------

BAD_GOTO_NODE = """
from app.graph.goto import goto

async def bad(state):
    return await goto(state, "S_X", next_node="n", step="B1", event="e",
                       resolution_path="auto")
"""

BAD_REASON_DETAIL_NODE = """
from app.graph.goto import goto

MOT_HANG_SO_LA = "chua_tung_duoc_chot"

async def bad(state):
    await goto(state, "S_X", next_node="n", step="B1", event="e",
               escalation_reason_detail="chua_co_trong_danh_sach")
    await goto(state, "S_X", next_node="n", step="B1", event="e",
               escalation_reason_detail=MOT_HANG_SO_LA)
"""


def test_checker_catches_unknown_state_key_in_goto() -> None:
    tree = ast.parse(BAD_GOTO_NODE)
    hits = _goto_fields_keywords(tree, "fake.py")
    assert hits == ["fake.py:5 resolution_path"]
    assert "resolution_path" not in STATE_KEYS


def test_checker_catches_unknown_reason_detail_including_via_constant() -> None:
    tree = ast.parse(BAD_REASON_DETAIL_NODE)
    values = [v for _, v in _reason_detail_values(tree, "fake.py")]
    assert values == ["chua_co_trong_danh_sach", "chua_tung_duoc_chot"]
    assert not any(v in REASON_DETAILS for v in values)
