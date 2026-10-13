"""P3 (PLAN-3f; phase3 3.2, G-01) — test AST: không đường nào đưa slot / đầu ra LLM vào `facts`.

- `graph/nodes/b03_classify.py`: mọi `facts=` truyền cho `goto` là `{}` trần; không gán tên `facts` ở đâu cả (B3 chỉ đặt lại).
- `graph/nodes/b06_diagnose.py`: tên `facts` CHỈ được gán bằng tách tuple từ `vpn.infer_vpn(...)`; `facts=` của `goto` là
  tên `facts` hoặc `{}`; không `facts[...] =`, `facts.update`, `facts |=`, không dựng dict có `**slots` cho `facts` (M-3f-2).
- `tools/diagnosis/vpn.py::infer_vpn`: vế phải của mọi `facts[...] = …` không nhắc tới `slots`, `raw`, `it`, `device_id`
  (mã máy người dùng nêu chỉ là KHOÁ TRA CỨU, không bao giờ là giá trị fact); `facts` khởi tạo `{}`.
- T20a (phase5 5.1.6 t2, PLAN-T20a TQ-5) — mở rộng: quét 4 file `tools/diagnosis/{vpn,account,software,access}.py`, hàm `infer_vpn`,
  `device_facts` (vpn.py), `infer_account`, `infer_software`, `infer_access`. Tên `facts` chỉ được gán `{}` hoặc là phần tử tuple
  nhận từ lời gọi `device_facts(...)`; vế phải `facts[...] = …` không chứa tên ∈ TAINTED cũ ∪ {name, path, software_name,
  resource_path, target_user, account_type, rf}; không `facts.update/setdefault/|=`. Mỗi hàm quét phải có ≥ 1 phép gán
  `facts[...]` (quét không rỗng) — bỏ ngưỡng cũ "infer_vpn ≥ 7" vì phần máy chuyển sang `device_facts`. B6: `facts` chỉ nhận từ
  tách tuple của lời gọi `.infer_vpn(...)` HOẶC `.infer(...)` (nhánh `DIAGNOSERS`).
- Siết khi duyệt DỪNG 1 (NGHI c của security-reviewer — agent chính viết): (1) TAINT LAN qua biến trung gian — tên nào được gán từ
  biểu thức có dùng tên đã nhiễm như GIÁ TRỊ thì cũng nhiễm (lặp tới điểm cố định; cả vòng `for`, `:=`); ngoại lệ DUY NHẤT là dùng làm
  KHOÁ LỌC: phép so có biến của chính comprehension trong điều kiện `if` (`[p for p in rows if p.path == path]`) hoặc tham số của
  `device_facts(...)` (hàm đã quét riêng). Soát S16 (N4) thêm: bí danh `f = facts`, khoá `facts[<tên nhiễm>]`. (2) Mọi câu `return` của hàm quét phải trả tuple 2 phần tử, phần tử 2 là đúng tên `facts`
  (chặn `return {}, {**slots}`). Không lần theo luồng điều khiển (`if path: facts[...] = True`) — giới hạn ghi ở "Spec cần sửa".
Mẫu giả cuối file chứng minh bộ kiểm bắt được vi phạm (khuôn `test_side_effects_ast.py`).
"""

import ast
from pathlib import Path
from typing import cast

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
B03 = APP / "graph" / "nodes" / "b03_classify.py"
B06 = APP / "graph" / "nodes" / "b06_diagnose.py"
DIAG = APP / "tools" / "diagnosis"
VPN = DIAG / "vpn.py"
TAINTED_3F = frozenset({"slots", "raw", "it", "out", "device_id", "clean", "added", "inferred"})
# T20a TQ-5: + tên slot/khoá tra cứu của 3 intent mới (`rf` = người bị tác động, chỉ là khoá tra)
TAINTED = TAINTED_3F | {"name", "path", "software_name", "resource_path", "target_user", "account_type", "rf"}
# T20a t2: (file, hàm) được quét
INFER_FUNCS = (
    ("vpn.py", "infer_vpn"), ("vpn.py", "device_facts"), ("account.py", "infer_account"),
    ("software.py", "infer_software"), ("access.py", "infer_access"),
)  # fmt: skip
B6_INFER_ATTRS = frozenset({"infer_vpn", "infer"})


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
                bad.append(f"dòng {cast(ast.stmt, node).lineno}: B3 gán facts")
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
                    bad.append(f"dòng {cast(ast.stmt, node).lineno}: facts[...] = …")
                elif isinstance(e, ast.Name) and e.id == "facts":
                    value = getattr(node, "value", None)
                    from_infer = (  # T20a: tách TUPLE từ `.infer_vpn(...)` hoặc `.infer(...)` (DIAGNOSERS)
                        isinstance(node, ast.Assign) and isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Attribute) and value.func.attr in B6_INFER_ATTRS
                        and all(isinstance(tg, ast.Tuple) for tg in node.targets)
                    )  # fmt: skip
                    if not from_infer:
                        bad.append(f"dòng {cast(ast.stmt, node).lineno}: facts gán ngoài infer_vpn/infer")
    return bad + [f"dòng {n}: facts.update…" for n in _mutating_calls(tree)]


def _calls_device_facts(value: ast.AST | None) -> bool:
    if not isinstance(value, ast.Call):
        return False
    f = value.func
    return (isinstance(f, ast.Name) and f.id == "device_facts") or (isinstance(f, ast.Attribute) and f.attr == "device_facts")


def _value_names(node: ast.AST) -> set[str]:
    """Tên dùng như GIÁ TRỊ trong biểu thức — bỏ qua điều kiện `if` của comprehension (khoá lọc) và lời gọi `device_facts(...)`."""
    out: set[str] = set()

    def visit(n: ast.AST) -> None:
        if _calls_device_facts(n):
            return
        if isinstance(n, ast.comprehension):
            visit(n.target)
            visit(n.iter)
            bound = _names(n.target)
            for cond in n.ifs:  # khoá lọc CHỈ khi là phép so có biến của chính comprehension (`p.path == path`)
                if not (isinstance(cond, ast.Compare) and _names(cond) & bound):
                    visit(cond)  # `if slots.get('a')` — điều kiện không lọc phần tử nào = rửa giá trị → tính là giá trị
            return
        if isinstance(n, ast.Name):
            out.add(n.id)
        for c in ast.iter_child_nodes(n):
            visit(c)

    visit(node)
    return out


def _tainted(fn: ast.FunctionDef) -> frozenset[str]:
    """TAINTED ∪ mọi tên (trừ `facts`) được gán từ biểu thức dùng tên nhiễm như giá trị — lặp tới điểm cố định."""
    tainted = set(TAINTED)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
                value, targets = node.value, ([node.target] if not isinstance(node, ast.Assign) else node.targets)
            elif isinstance(node, ast.For):
                value, targets = node.iter, [node.target]
            else:
                continue
            if value is None or not _value_names(value) & tainted:
                continue
            for t in targets:
                for e in _flat(t):
                    if isinstance(e, ast.Name) and e.id != "facts" and e.id not in tainted:
                        tainted.add(e.id)
                        changed = True
    return frozenset(tainted)


def _bad_returns(fn: ast.FunctionDef) -> list[str]:
    """Mọi `return` phải là tuple 2 phần tử, phần tử 2 đúng tên `facts`."""
    return [
        f"dòng {r.lineno}: return không trả (…, facts)" for r in ast.walk(fn) if isinstance(r, ast.Return)
        and not (isinstance(r.value, ast.Tuple) and len(r.value.elts) == 2
                 and isinstance(r.value.elts[1], ast.Name) and r.value.elts[1].id == "facts")
    ]  # fmt: skip


def _infer_fn(tree: ast.AST, name: str) -> ast.FunctionDef:
    [fn] = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == name]
    return fn


def check_infer(src: str, name: str = "infer_vpn") -> list[str]:
    """Hàm `name` trong `src`: `facts` chỉ gán `{}` hoặc là phần tử tuple từ `device_facts(...)`; vế phải `facts[...] = …` không
    nhắc tên nhiễm (TAINTED + lan qua biến trung gian); không facts.update/setdefault/|=; `return` trả (…, facts)."""
    fn = _infer_fn(ast.parse(src), name)
    tainted = _tainted(fn)
    bad: list[str] = _bad_returns(fn)
    for node in ast.walk(fn):
        for t in _targets(node):
            for e in _flat(t):
                value = getattr(node, "value", None)
                if isinstance(e, ast.Subscript) and isinstance(e.value, ast.Name) and e.value.id == "facts":
                    if value is not None and (hit := _names(value) & tainted):
                        bad.append(f"dòng {cast(ast.stmt, node).lineno}: facts[...] lấy từ {sorted(hit)}")
                    if hit := _names(e.slice) & tainted:  # khoá fact lấy từ slot (`facts[slots['k']] = True`)
                        bad.append(f"dòng {cast(ast.stmt, node).lineno}: khoá facts[...] lấy từ {sorted(hit)}")
                elif isinstance(e, ast.Name) and e.id != "facts" and isinstance(value, ast.Name) and value.id == "facts":
                    bad.append(f"dòng {cast(ast.stmt, node).lineno}: bí danh của facts ({e.id} = facts)")
                elif isinstance(e, ast.Name) and e.id == "facts":
                    empty = value is not None and _is_empty_dict(value) and not isinstance(node, ast.AugAssign)
                    from_device = (isinstance(node, ast.Assign) and isinstance(t, ast.Tuple)
                                   and _calls_device_facts(value))  # fmt: skip
                    if not (empty or from_device):
                        bad.append(f"dòng {cast(ast.stmt, node).lineno}: facts khởi tạo khác {{}} / device_facts(...)")
    return bad + [f"dòng {n}: facts.update…" for n in _mutating_calls(fn)]


def _fact_writes(src: str, name: str) -> list[ast.stmt]:
    fn = _infer_fn(ast.parse(src), name)
    return [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
            and any(isinstance(e, ast.Subscript) and isinstance(e.value, ast.Name) and e.value.id == "facts"
                    for t in n.targets for e in _flat(t))]  # fmt: skip


def test_p3_b03_never_writes_facts() -> None:
    src = B03.read_text(encoding="utf-8")
    assert _facts_keywords(ast.parse(src))  # quét không rỗng: B3 có đặt lại facts={}
    assert check_b03(src) == []


def test_p3_b06_facts_only_from_infer_vpn() -> None:
    src = B06.read_text(encoding="utf-8")
    assert len(_facts_keywords(ast.parse(src))) >= 2
    assert check_b06(src) == []


def test_p3_infer_vpn_facts_never_from_slots() -> None:
    """Đổi ở T20a (TQ-5): ngưỡng "≥ 7 phép gán" → "≥ 1" (phần máy chuyển sang `device_facts`, quét ở t2); TAINTED mở rộng."""
    src = VPN.read_text(encoding="utf-8")
    assert len(_fact_writes(src, "infer_vpn")) >= 1  # quét không rỗng
    assert check_infer(src) == []


@pytest.mark.parametrize(("file", "name"), INFER_FUNCS, ids=[f"t2-{f}-{n}" for f, n in INFER_FUNCS])
def test_t2_infer_facts_never_from_slots(file: str, name: str) -> None:
    """P3 + T20a t2 (TQ-5): mỗi hàm quét có ≥ 1 phép gán `facts[...]` (quét không rỗng) và không vi phạm."""
    src = (DIAG / file).read_text(encoding="utf-8")
    assert len(_fact_writes(src, name)) >= 1, f"{file}::{name} không có phép gán facts[...] nào (quét rỗng)"
    assert check_infer(src, name) == []


def test_t2_four_diagnosis_files_scanned() -> None:
    """t2: đúng 4 file `tools/diagnosis/*.py` (trừ `__init__`) đều nằm trong phạm vi quét."""
    files = sorted(p.name for p in DIAG.glob("*.py") if p.name != "__init__.py")
    assert files == sorted({f for f, _ in INFER_FUNCS}) == ["access.py", "account.py", "software.py", "vpn.py"]


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


def test_t2_checkers_catch_violations() -> None:
    """T20a t2: mẫu giả cho phần mở rộng — bộ kiểm bắt được."""
    # B6 nhánh DIAGNOSERS: hợp lệ khi tách tuple từ `.infer(...)`; gán thẳng / dựng dict từ slot → bắt
    assert check_b06("def f(m, d):\n    _, facts = m.infer(d, requester_id='x', slots={})\n") == []
    assert check_b06("def f(m, d):\n    facts = m.infer(d)\n")
    assert check_b06("def f(m, d, slots):\n    _, facts = m.infer(d)\n    facts['x'] = slots['x']\n")
    assert check_b06("def f(m, d):\n    _, facts = m.diagnose(d)\n")
    # infer_* mới: slot làm giá trị fact
    ok = "def infer_access(d, *, requester_id, slots):\n    facts = {}\n    facts['resource_sensitivity'] = d['r'].sensitivity\n"
    assert check_infer(ok, "infer_access") == []
    assert check_infer("def infer_access(d, *, requester_id, slots):\n    path = slots['resource_path']\n"
                       "    facts = {}\n    facts['resource_sensitivity'] = path\n", "infer_access")  # fmt: skip
    assert check_infer("def infer_account(d, *, requester_id, slots):\n    rf = slots.get('target_user')\n"
                       "    facts = {}\n    facts['target_user_status'] = rf\n", "infer_account")  # fmt: skip
    assert check_infer("def infer_software(d, *, requester_id, slots):\n    name = slots['software_name']\n"
                       "    facts = {}\n    facts['in_catalog'] = name == 'zoom'\n", "infer_software")  # fmt: skip
    assert check_infer("def infer_account(d, *, requester_id, slots):\n    facts = {}\n"
                       "    facts['target_account_privilege'] = account_type\n", "infer_account")  # fmt: skip
    # `facts` chỉ từ `{}` hoặc tuple của device_facts(...)
    assert check_infer("def infer_software(d, *, requester_id, slots):\n"
                       "    slots2, facts = device_facts(d['x'], requester_id=requester_id, device_id=None)\n"
                       "    facts['in_catalog'] = True\n", "infer_software") == []  # fmt: skip
    assert check_infer("def infer_software(d, *, requester_id, slots):\n    facts = helper(d)\n", "infer_software")
    assert check_infer("def infer_software(d, *, requester_id, slots):\n    facts = device_facts(d)\n", "infer_software")
    assert check_infer("def infer_software(d, *, requester_id, slots):\n    facts = {}\n    facts |= slots\n",
                       "infer_software")  # fmt: skip
    assert check_infer("def infer_access(d, *, requester_id, slots):\n    facts = {}\n    facts.setdefault('x', 1)\n",
                       "infer_access")  # fmt: skip
    assert check_infer("def device_facts(devices, *, requester_id, device_id):\n    facts = {}\n"
                       "    facts['device_registered'] = device_id is not None\n", "device_facts")  # fmt: skip
    # quét không rỗng: hàm không có phép gán nào → 0 phép gán (test t2 đòi ≥ 1)
    assert _fact_writes("def infer_access(d, *, requester_id, slots):\n    return {}, {}\n", "infer_access") == []


def test_t2_checkers_catch_laundering_and_returns() -> None:
    """Siết NGHI c (duyệt DỪNG 1): taint lan qua biến trung gian / vòng for / `:=`; `return` phải trả đúng tên `facts`. Khoá lọc trong
    điều kiện comprehension và tham số `device_facts(...)` KHÔNG làm nhiễm (code thật dùng — không báo nhầm)."""
    head = "def infer_access(d, *, requester_id, slots):\n"
    # lan qua biến trung gian (tên không nằm trong TAINTED gốc)
    assert check_infer(head + "    x = slots['resource_path']\n    y = x.lower()\n    facts = {}\n"
                       "    facts['resource_sensitivity'] = y\n    return {}, facts\n", "infer_access")  # fmt: skip
    assert check_infer(head + "    alias = slots\n    facts = {}\n    facts['in_catalog'] = alias.get('n') == 'zoom'\n"
                       "    return {}, facts\n", "infer_access")  # fmt: skip
    assert check_infer(head + "    flag = slots.get('action') == 'grant_permission'\n    facts = {}\n"
                       "    facts['has_permission_record'] = flag\n    return {}, facts\n", "infer_access")  # fmt: skip
    assert check_infer(head + "    facts = {}\n    for v in slots.values():\n        facts['resource_sensitivity'] = v\n"
                       "    return {}, facts\n", "infer_access")  # fmt: skip
    assert check_infer(head + "    facts = {}\n    if (p := slots.get('x')):\n        facts['resource_sensitivity'] = p\n"
                       "    return {}, facts\n", "infer_access")  # fmt: skip
    # soát S16 (N4): bí danh facts, khoá từ slot, rửa qua `if` không lọc phần tử
    assert check_infer(head + "    facts = {}\n    f = facts\n    f['x'] = slots['x']\n    return {}, facts\n", "infer_access")
    assert check_infer(head + "    facts = {}\n    facts[slots['k']] = True\n    return {}, facts\n", "infer_access")
    assert check_infer(head + "    facts = {}\n    flag = any(True for _ in [0] if slots.get('a'))\n"
                       "    facts['has_permission_record'] = flag\n    return {}, facts\n", "infer_access")  # fmt: skip
    # return không trả đúng tên facts
    assert check_infer(head + "    facts = {}\n    facts['x'] = d['r'].v\n    return {}, {**slots}\n", "infer_access")
    assert check_infer(head + "    facts = {}\n    facts['x'] = d['r'].v\n    return {}, dict(slots)\n", "infer_access")
    assert check_infer(head + "    facts = {}\n    facts['x'] = d['r'].v\n    return facts\n", "infer_access")
    # KHÔNG báo nhầm: khoá lọc trong comprehension / next(generator), tham số device_facts
    ok = (head + "    path = slots.get('resource_path')\n    perms = d['p']\n    facts = {}\n"
          "    rows = [p for p in perms.root if p.path == path]\n    facts['has_permission_record'] = bool(rows)\n"
          "    dev = next((x for x in d['devs'] if x.device_id == slots.get('device_id')), None)\n"
          "    facts['device_registered'] = dev is not None and dev.registered\n    return {}, facts\n")  # fmt: skip
    assert check_infer(ok, "infer_access") == []
    ok_dev = ("def infer_software(d, *, requester_id, slots):\n"
              "    inferred, facts = device_facts(d['x'], requester_id=requester_id, device_id=slots.get('device_id'))\n"
              "    facts['in_catalog'] = d['c'] is not None\n    return inferred, facts\n")  # fmt: skip
    assert check_infer(ok_dev, "infer_software") == []
