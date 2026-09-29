"""P3 (PLAN-3f; phase3 3.2, G-01) — test AST: không đường nào đưa slot / đầu ra LLM vào `facts`.

- `graph/nodes/b03_classify.py`: mọi `facts=` truyền cho `goto` là `{}` trần; không gán tên `facts` ở đâu cả (B3 chỉ đặt lại).
- `graph/nodes/b06_diagnose.py`: tên `facts` CHỈ được gán bằng tách tuple từ `vpn.infer_vpn(...)`; `facts=` của `goto` là
  tên `facts` hoặc `{}`; không `facts[...] =`, `facts.update`, `facts |=`, không dựng dict có `**slots` cho `facts` (M-3f-2).
- `tools/diagnosis/vpn.py::infer_vpn`: vế phải của mọi `facts[...] = …` không nhắc tới `slots`, `raw`, `it`, `device_id`
  (mã máy người dùng nêu chỉ là KHOÁ TRA CỨU, không bao giờ là giá trị fact); `facts` khởi tạo `{}`.
Mẫu giả cuối file chứng minh bộ kiểm bắt được vi phạm (khuôn `test_side_effects_ast.py`).
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
B03 = APP / "graph" / "nodes" / "b03_classify.py"
B06 = APP / "graph" / "nodes" / "b06_diagnose.py"
VPN = APP / "tools" / "diagnosis" / "vpn.py"
TAINTED = frozenset({"slots", "raw", "it", "out", "device_id", "clean", "added", "inferred"})


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _is_empty_dict(node: ast.AST) -> bool:
    return isinstance(node, ast.Dict) and not node.keys


def _targets(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AugAssign | ast.AnnAssign):
        return [node.target]
    return []


def _flat(target: ast.expr) -> list[ast.expr]:
    return [t for e in ast.walk(target) if isinstance(e, ast.Tuple | ast.List) for t in e.elts] or [target]


def _facts_keywords(tree: ast.AST) -> list[ast.keyword]:
    return [k for c in ast.walk(tree) if isinstance(c, ast.Call) for k in c.keywords if k.arg == "facts"]


def _mutating_calls(tree: ast.AST) -> list[int]:
    return [
        c.lineno for c in ast.walk(tree)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)
        and c.func.value.id == "facts" and c.func.attr in {"update", "setdefault", "__setitem__", "__ior__"}
    ]  # fmt: skip


def check_b03(src: str) -> list[str]:
    tree = ast.parse(src)
    bad = [f"dòng {k.value.lineno}: facts= không phải {{}}" for k in _facts_keywords(tree) if not _is_empty_dict(k.value)]
    for node in ast.walk(tree):
        for t in _targets(node):
            if any(isinstance(e, ast.Name) and e.id == "facts" or isinstance(e, ast.Subscript) for e in _flat(t)
                   if "facts" in _names(e)):  # fmt: skip
                bad.append(f"dòng {node.lineno}: B3 gán facts")
    return bad + [f"dòng {n}: facts.update…" for n in _mutating_calls(tree)]


def check_b06(src: str) -> list[str]:
    tree = ast.parse(src)
    bad: list[str] = []
    for k in _facts_keywords(tree):
        if not (_is_empty_dict(k.value) or (isinstance(k.value, ast.Name) and k.value.id == "facts")):
            bad.append(f"dòng {k.value.lineno}: facts= phải là tên facts hoặc {{}}")
    for node in ast.walk(tree):
        for t in _targets(node):
            for e in _flat(t):
                if isinstance(e, ast.Subscript) and "facts" in _names(e.value):
                    bad.append(f"dòng {node.lineno}: facts[...] = …")
                elif isinstance(e, ast.Name) and e.id == "facts":
                    value = getattr(node, "value", None)
                    from_infer = (
                        isinstance(node, ast.Assign) and isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Attribute) and value.func.attr == "infer_vpn"
                    )  # fmt: skip
                    if not from_infer:
                        bad.append(f"dòng {node.lineno}: facts gán ngoài infer_vpn")
    return bad + [f"dòng {n}: facts.update…" for n in _mutating_calls(tree)]


def check_infer(src: str) -> list[str]:
    tree = ast.parse(src)
    [fn] = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "infer_vpn"]
    bad: list[str] = []
    for node in ast.walk(fn):
        for t in _targets(node):
            for e in _flat(t):
                value = getattr(node, "value", None)
                if isinstance(e, ast.Subscript) and isinstance(e.value, ast.Name) and e.value.id == "facts":
                    if value is not None and (hit := _names(value) & TAINTED):
                        bad.append(f"dòng {node.lineno}: facts[...] lấy từ {sorted(hit)}")
                elif isinstance(e, ast.Name) and e.id == "facts" and not (value is not None and _is_empty_dict(value)):
                    bad.append(f"dòng {node.lineno}: facts khởi tạo khác {{}}")
    return bad + [f"dòng {n}: facts.update…" for n in _mutating_calls(fn)]


def test_p3_b03_never_writes_facts() -> None:
    src = B03.read_text(encoding="utf-8")
    assert _facts_keywords(ast.parse(src))  # quét không rỗng: B3 có đặt lại facts={}
    assert check_b03(src) == []


def test_p3_b06_facts_only_from_infer_vpn() -> None:
    src = B06.read_text(encoding="utf-8")
    assert len(_facts_keywords(ast.parse(src))) >= 2
    assert check_b06(src) == []


def test_p3_infer_vpn_facts_never_from_slots() -> None:
    src = VPN.read_text(encoding="utf-8")
    fn = next(f for f in ast.walk(ast.parse(src)) if isinstance(f, ast.FunctionDef) and f.name == "infer_vpn")
    writes = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Subscript) and "facts" in _names(t) for t in n.targets)]  # fmt: skip
    assert len(writes) >= 7  # quét không rỗng
    assert check_infer(src) == []


# ---- mẫu giả: bộ kiểm bắt được -------------------------------------------------------------------------------------------


def test_checkers_catch_violations() -> None:
    assert check_b03("async def f(s):\n    return await goto(s, S, facts=dict(s['slots']))\n")
    assert check_b03("def f(it):\n    facts = {}\n    facts['device_registered'] = it.slots['x']\n")
    # M-3f-2
    assert check_b06("def f(slots, facts):\n    facts = {**slots, **facts}\n")
    assert check_b06("def f(slots):\n    _, facts = vpn.infer_vpn(d)\n    facts.update(slots)\n")
    assert check_b06("def f(slots):\n    _, facts = vpn.infer_vpn(d)\n    facts['x'] = slots['x']\n")
    assert check_b06("async def f(s, slots):\n    return await goto(s, S, facts={**slots})\n")
    assert check_infer("def infer_vpn(d, *, slots, device_id):\n    facts = {}\n    facts['device_registered'] = slots['r']\n")
    assert check_infer("def infer_vpn(d, *, device_id):\n    facts = {}\n    facts['cert_status'] = device_id\n")
    assert check_infer("def infer_vpn(d, *, raw):\n    facts = dict(raw)\n")
