"""Bất biến M5 [Chốt]: policy_engine.evaluate(action, ctx) chỉ 2 tham số, và risk/ không
đụng tới raw_request (phần import-linter không bắt được — 01 mục 4.3)."""

import ast
import inspect
from pathlib import Path

import app.risk
import pytest
from app.risk import policy_engine


def test_evaluate_takes_only_action_and_ctx() -> None:
    params = inspect.signature(policy_engine.evaluate).parameters
    assert list(params) == ["action", "ctx"]
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in params.values())


def test_risk_never_mentions_raw_request() -> None:
    risk_dir = Path(app.risk.__file__).parent
    files = sorted(risk_dir.rglob("*.py"))
    assert files, "không thấy file nào trong app/risk"
    offenders = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            name = (
                node.id if isinstance(node, ast.Name)
                else node.attr if isinstance(node, ast.Attribute)
                else node.arg if isinstance(node, ast.arg)
                else node.value if isinstance(node, ast.Constant) and isinstance(node.value, str)
                else None
            )  # fmt: skip
            if name == "raw_request":
                offenders.append(f"{path.name}:{getattr(node, 'lineno', '?')}")
    assert offenders == []


# ---- h21 (phase3 11.3, 11.7; PLAN-3h P2): build_ctx chỉ đọc intended_action, requester_context, ctx_flags ----------

BUILD_CTX_KEYS = frozenset({"intended_action", "requester_context", "ctx_flags"})
USER_TEXT_KEYS = frozenset({"redacted_request", "conversation", "slots"})


def _build_ctx_fn() -> ast.FunctionDef:
    tree = ast.parse((Path(app.risk.__file__).parent / "context.py").read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_ctx"]
    assert len(fns) == 1, "risk/context.py phải có đúng một hàm build_ctx"
    return fns[0]


def _state_keys(fn: ast.FunctionDef) -> set[str]:
    """Khoá state đọc trong build_ctx. FAIL-CLOSED (siết sau soát S7): MỌI lần dùng `state` phải là `state["hằng"]` hoặc
    `state.get("hằng", …)` — truyền `state` cho hàm phụ, gán bí danh, `state.items()`, `dict(state)`, `**state` → đỏ."""
    param = fn.args.args[0].arg
    parent = {id(c): p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}
    keys: set[str] = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Name) and node.id == param):
            continue
        up = parent.get(id(node))
        if isinstance(up, ast.Subscript) and up.value is node and isinstance(node.ctx, ast.Load):
            assert isinstance(up.slice, ast.Constant) and isinstance(up.slice.value, str), "state[...] phải là khoá hằng"
            keys.add(up.slice.value)
            continue
        call = parent.get(id(up)) if isinstance(up, ast.Attribute) else None
        if isinstance(up, ast.Attribute) and up.attr == "get" and isinstance(call, ast.Call) and call.func is up:
            assert call.args and isinstance(call.args[0], ast.Constant), "state.get(...) phải là khoá hằng"
            keys.add(str(call.args[0].value))
            continue
        raise AssertionError(f"build_ctx dùng state ngoài dạng state[k]/state.get(k) (dòng {node.lineno})")
    return keys


def test_h21_build_ctx_reads_only_action_requester_flags() -> None:
    fn = _build_ctx_fn()
    keys = _state_keys(fn)
    assert keys, "không quét được khoá nào — bộ quét hỏng (quy ước 3.9)"
    assert keys <= BUILD_CTX_KEYS, f"build_ctx đọc khoá ngoài danh sách: {sorted(keys - BUILD_CTX_KEYS)}"
    assert {"intended_action", "requester_context"} <= keys


def test_h21_build_ctx_never_mentions_user_text() -> None:
    fn = _build_ctx_fn()
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)} | {
        str(n.value) for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip
    assert not names & USER_TEXT_KEYS, sorted(names & USER_TEXT_KEYS)
    # tham số: state + giờ + giờ hành chính — không có đường nào đưa chữ người dùng vào riêng
    assert [a.arg for a in fn.args.args] == ["state", "now", "hours"]


def _fn(src: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "build_ctx")


def test_h21_scanner_catches_slots_read() -> None:
    """Đối chứng: bộ quét bắt được `state["slots"]` (M-3h-8 dạng AST)."""
    fn = _fn('def build_ctx(state, now, hours):\n    return state["slots"], state.get("intended_action")\n')
    assert "slots" in _state_keys(fn)


@pytest.mark.parametrize(
    "body",
    ["return helper(state)", "s = state\n    return s['slots']", "return dict(state)", "return list(state.items())",
     "return f(**state)", "return state[key]", "state = {}\n    return state"],
    ids=["ham-phu", "bi-danh", "dict", "items", "spread", "khoa-bien", "gan-lai"],
)
def test_h21_scanner_rejects_indirect_state_use(body: str) -> None:
    """Đối chứng (soát S7 NGHI): mọi đường đọc state gián tiếp → đỏ thay vì lọt im lặng."""
    with pytest.raises(AssertionError):
        _state_keys(_fn(f"def build_ctx(state, now, hours):\n    {body}\n"))
