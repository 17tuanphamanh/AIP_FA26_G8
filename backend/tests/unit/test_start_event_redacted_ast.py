"""N1 (PROGRESS "Việc treo" 15; phase3 10.7 #13; PLAN-3h S5) — mọi sự kiện resume mang chữ người dùng phải được che L1
(`redact(...)`) TRƯỚC khi vào runner: LangGraph lưu giá trị resume vào checkpoint trước khi node chạy, node không che kịp.

Hiện có đúng 3 nơi (đều đã che): `/messages` `text` và `/confirm` `note` (`api/tickets.py`), route duyệt `note`
(`api/approvals.py`). Test để người sau sửa route (hay thêm nơi tạo sự kiện mới) mà bỏ bước che thì đỏ ngay.

Bộ quét FAIL-CLOSED (siết sau soát S7 — 9 dạng lọt im lặng của bản đầu):
1. Cổng resume = `SINKS` (`start_event`, `deliver_event`, `resume`, `resume_locked`). Không được import bí danh, truyền hàm cổng
   như giá trị (`partial`, `getattr`) — dạng đó đỏ.
2. Đối số sự kiện: dict literal, hoặc tên gán ĐÚNG MỘT LẦN từ dict literal và không bị sửa sau (`ev["k"] = …`, `.update`,
   `|=`), hoặc tham số của chính một hàm cổng (chuyển tiếp — nơi tạo gốc đã được quét). Dạng khác → đỏ.
3. Mọi khoá là chuỗi hằng (không `**`, không khoá biến). Khoá thuộc `TYPED_KEYS` (giá trị kiểu chặt do model API ép: enum,
   định danh token, thời điểm server) được tự do; MỌI khoá khác phải là hằng hoặc dẫn xuất CHỈ từ kết quả `redact(...)`.
4. "Sạch" = tên mà MỌI lần gán trong hàm đều là `[await] redact(...)` (hoặc `… if … else None`) hoặc chỉ dùng tên sạch;
   `redact` phải là hàm import từ `app.api.desk` (không tin theo tên); lời gọi `redact` đứng trước cổng.
5. Mỗi lời gọi cổng xét riêng (không gộp theo tên hàm).
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import app
import pytest

APP = Path(app.__file__).parent
SINKS = frozenset({"start_event", "deliver_event", "resume", "resume_locked"})
EVENT_ARG = {"start_event": 3, "deliver_event": 3, "resume": 1, "resume_locked": 1}  # vị trí đối số sự kiện
TYPED_KEYS = frozenset({"kind", "approver_id", "at", "reason_code", "view_duration"})
# 4c P4 (soát S11 R1): `decided_as` KHÔNG miễn theo tên khoá (toàn cục) — chỉ nhận một TÊN mà MỌI lần gán trong hàm, trước cổng, là
# `approval_role(...)` import thẳng từ `app.auth.authz` (Literal "primary" | "backup" do server tính).
ROLE_KEYS = frozenset({"decided_as"})
ROLE_FUNC, ROLE_MODULE = "approval_role", "app.auth.authz"
REDACT_MODULE = "app.api.desk"
EXPECTED_USER_TEXT = {
    ("api/tickets.py", "post_message", "text"), ("api/tickets.py", "confirm", "note"),
    ("api/approvals.py", "decide", "note"),
}  # fmt: skip

type Fn = ast.FunctionDef | ast.AsyncFunctionDef


class Unparsable(AssertionError):
    """Dạng code bộ quét không chứng minh được là an toàn → đỏ (fail-closed)."""


def _sink_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
    return name if name in SINKS else None


def _functions(tree: ast.AST) -> Iterator[tuple[Fn, list[Fn]]]:
    """(hàm, chuỗi hàm bao ngoài từ trong ra) — để nhận tham số chuyển tiếp của hàm cổng bao ngoài."""

    def walk(node: ast.AST, outer: list[Fn]) -> Iterator[tuple[Fn, list[Fn]]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield child, outer
                yield from walk(child, [child, *outer])
            else:
                yield from walk(child, outer)

    yield from walk(tree, [])


def _own_nodes(fn: Fn) -> Iterator[ast.AST]:
    """Nút thuộc thân hàm, KHÔNG đi vào hàm lồng (hàm lồng xét riêng)."""
    stack: list[ast.AST] = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            stack.extend(ast.iter_child_nodes(node))


def _params(fn: Fn) -> set[str]:
    a = fn.args
    return {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]}


def _redact_trusted(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.ImportFrom) and n.module == REDACT_MODULE
        and any(a.name == "redact" and a.asname is None for a in n.names)
        for n in tree.body
    )  # fmt: skip


def _is_redact_form(value: ast.expr, trusted: bool) -> bool:
    """`[await] redact(...)` hoặc `[await] redact(...) if … else None` — không nhận biểu thức trộn."""

    def call(e: ast.expr) -> bool:
        e = e.value if isinstance(e, ast.Await) else e
        return trusted and isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "redact"

    if isinstance(value, ast.IfExp):
        return call(value.body) and isinstance(value.orelse, ast.Constant) and value.orelse.value is None
    return call(value)


def _bindings(fn: Fn) -> tuple[dict[str, list[tuple[ast.expr, int]]], set[str]]:
    """Tên → [(giá trị, dòng)] của các lệnh `x = …`; và tập tên bị gán theo dạng khác (bị coi là không sạch)."""
    simple: dict[str, list[tuple[ast.expr, int]]] = {}
    other: set[str] = set()
    for n in _own_nodes(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    simple.setdefault(t.id, []).append((n.value, n.lineno))
                else:
                    other |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
        elif isinstance(n, ast.AugAssign | ast.AnnAssign | ast.For | ast.AsyncFor | ast.NamedExpr | ast.withitem):
            target = n.optional_vars if isinstance(n, ast.withitem) else n.target
            if target is not None:
                other |= {x.id for x in ast.walk(target) if isinstance(x, ast.Name)}
    return simple, other


def _clean(fn: Fn, before: int, trusted: bool) -> set[str]:
    simple, other = _bindings(fn)
    clean: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, assigns in simple.items():
            if name in clean or name in other:
                continue

            def ok(value: ast.expr) -> bool:
                used = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
                return _is_redact_form(value, trusted) or bool(used) and used <= clean

            if all(line < before for _, line in assigns) and all(ok(v) for v, _ in assigns):
                clean.add(name)
                changed = True
    return clean


def _role_names(tree: ast.Module, fn: Fn, before: int) -> set[str]:
    """Tên chỉ được gán từ `approval_role(...)` (import thẳng, không bí danh) trước cổng — giá trị kiểu chặt do server tính."""
    if not any(
        isinstance(n, ast.ImportFrom) and n.module == ROLE_MODULE and any(a.name == ROLE_FUNC and a.asname is None for a in n.names)
        for n in tree.body
    ):
        return set()
    simple, other = _bindings(fn)

    def is_role(value: ast.expr) -> bool:
        value = value.value if isinstance(value, ast.Await) else value
        return isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == ROLE_FUNC

    return {name for name, assigns in simple.items()
            if name not in other and all(line < before for _, line in assigns) and all(is_role(v) for v, _ in assigns)}  # fmt: skip


def _mutated(fn: Fn, name: str) -> bool:
    for n in _own_nodes(fn):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store | ast.Del) and isinstance(n.value, ast.Name) \
                and n.value.id == name:  # fmt: skip
            return True
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and n.target.id == name:
            return True
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                and n.func.value.id == name and n.func.attr in {"update", "setdefault", "__setitem__", "__ior__"}):  # fmt: skip
            return True
    return False


def _event(fn: Fn, outer: list[Fn], call: ast.Call, sink: str) -> ast.Dict | None:
    """Dict sự kiện; None = chuyển tiếp tham số của một hàm cổng (nơi tạo gốc được quét riêng)."""
    idx = EVENT_ARG[sink]
    arg = call.args[idx] if len(call.args) > idx else next((k.value for k in call.keywords if k.arg == "event"), None)
    if any(k.arg is None for k in call.keywords) or any(isinstance(a, ast.Starred) for a in call.args):
        raise Unparsable(f"{fn.name}:{call.lineno}: {sink} với *args/**kwargs")
    if isinstance(arg, ast.Dict):
        return arg
    if isinstance(arg, ast.Name):
        for f in [fn, *outer]:
            if arg.id in _params(f):
                if f.name in SINKS:
                    return None  # chuyển tiếp trong chính cổng (late_event, runner)
                raise Unparsable(f"{fn.name}:{call.lineno}: sự kiện là tham số của {f.name} (không phải cổng)")
        simple, other = _bindings(fn)
        bound = simple.get(arg.id, [])
        if len(bound) == 1 and arg.id not in other and isinstance(bound[0][0], ast.Dict) \
                and bound[0][1] < call.lineno and not _mutated(fn, arg.id):  # fmt: skip
            return bound[0][0]
    raise Unparsable(f"{fn.name}:{call.lineno}: không phân tích được sự kiện của {sink}")


def check_call(tree: ast.Module, fn: Fn, outer: list[Fn], call: ast.Call) -> tuple[list[str], list[str]]:
    """(khoá chữ tự do đã che, khoá chữ tự do KHÔNG đi qua `redact` trước cổng). Dạng lạ → `Unparsable`."""
    sink = _sink_name(call)
    assert sink is not None
    event = _event(fn, outer, call, sink)
    if event is None:
        return [], []
    clean = _clean(fn, call.lineno, _redact_trusted(tree))
    roles = _role_names(tree, fn, call.lineno)
    free: list[str] = []
    bad: list[str] = []
    for key, value in zip(event.keys, event.values, strict=True):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            raise Unparsable(f"{fn.name}:{call.lineno}: khoá sự kiện không phải chuỗi hằng (hoặc `**`)")
        if key.value in TYPED_KEYS or isinstance(value, ast.Constant):
            continue
        if key.value in ROLE_KEYS and isinstance(value, ast.Name) and value.id in roles:
            continue
        used = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
        (free if used and used <= clean else bad).append(key.value)
    return free, bad


def _sink_references(tree: ast.Module) -> list[str]:
    """Hàm cổng bị import bí danh hoặc dùng như giá trị (partial, getattr, gán tên) — né được bộ quét → đỏ."""
    bad: list[str] = []
    call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom | ast.Import):
            bad += [f"import {a.name} as {a.asname}" for a in n.names if a.name in SINKS and a.asname]
        elif isinstance(n, ast.Name) and n.id in SINKS and isinstance(n.ctx, ast.Load) and id(n) not in call_funcs:
            bad.append(f"{n.id} dùng như giá trị (dòng {n.lineno})")
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr" and len(n.args) > 1
              and isinstance(n.args[1], ast.Constant) and n.args[1].value in SINKS):  # fmt: skip
            bad.append(f"getattr(…, {n.args[1].value!r}) (dòng {n.lineno})")
    return bad


def scan(tree: ast.Module) -> dict[tuple[str, int], tuple[list[str], list[str]]]:
    out: dict[tuple[str, int], tuple[list[str], list[str]]] = {}
    for fn, outer in _functions(tree):
        for node in _own_nodes(fn):
            if _sink_name(node) is not None:
                assert isinstance(node, ast.Call)
                out[(fn.name, node.lineno)] = check_call(tree, fn, outer, node)
    return out


def _app_trees() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(APP.rglob("*.py")):
        yield str(path.relative_to(APP)), ast.parse(path.read_text(encoding="utf-8"))


def test_n1_user_text_events_are_redacted_first() -> None:
    found: set[tuple[str, str, str]] = set()
    bad: dict[tuple[str, str, int], list[str]] = {}
    calls = 0
    for rel, tree in _app_trees():
        for (fn, line), (free, not_clean) in scan(tree).items():
            calls += 1
            found |= {(rel, fn, k) for k in free}
            if not_clean:
                bad[(rel, fn, line)] = not_clean
    assert calls >= 7, "bộ quét thấy quá ít lời gọi cổng resume (quy ước 3.9)"
    assert bad == {}, f"sự kiện có chữ tự do KHÔNG qua redact trước cổng: {bad}"
    assert found == EXPECTED_USER_TEXT, f"nơi tạo sự kiện có chữ người dùng đổi — soát bước che rồi sửa EXPECTED: {found}"


def test_n1_sinks_never_aliased_or_passed_around() -> None:
    refs = {rel: r for rel, tree in _app_trees() if (r := _sink_references(tree))}
    assert refs == {}


# ---- Đối chứng: mỗi dạng lọt của bản đầu (soát S7) giờ đỏ; khuôn route thật thì đạt ----------------------------------

_HEAD = "from app.api.desk import redact\nfrom app.graph.late_event import start_event\n"
_GOOD = _HEAD + '''
async def confirm(desk, body):
    redacted = await redact(desk, body.note) if body.note else None
    note = redacted.text if redacted is not None else None
    event = {"kind": "confirmed", "note": note, "approver_id": body.who}
    await start_event(desk.runner, "t", "S", event)
'''
_BAD = {
    "raw": ('await start_event(r, "t", "S", {"kind": "user_reply", "text": body.text})', ["text"]),
    "late": ('note = body.note\n    await start_event(r, "t", "S", {"note": note})\n    x = await redact(d, note)', ["note"]),
    "khoa-khac": ('await start_event(r, "t", "S", {"kind": "x", "comment": body.comment})', ["comment"]),
    "gan-lai-ten-sach": (('redacted = await redact(d, body.text)\n    redacted = body\n'
                          '    await start_event(r, "t", "S", {"text": redacted.text})'), ["text"]),
    "bieu-thuc-tron": (('text = body.text if await redact(d, body.text) else ""\n'
                        '    await start_event(r, "t", "S", {"text": text})'), ["text"]),
    "hai-cong-mot-ham": (('redacted = await redact(d, body.text)\n    await start_event(r, "t", "S", {"text": body.text})\n'
                          '    if x:\n        await start_event(r, "t", "S", {"text": redacted.text})'), ["text"]),
    "deliver": ('await deliver_event(r, "t", "S", {"kind": "user_reply", "text": body.text})', ["text"]),
    "resume": ('await runner.resume("t", {"kind": "user_reply", "text": body.text})', ["text"]),
}
_UNPARSABLE = {
    "spread": 'await start_event(r, "t", "S", {"kind": "user_reply", **body.model_dump()})',
    "khoa-bien": 'await start_event(r, "t", "S", {TEXT: body.text})',
    "sua-sau": 'ev = {"kind": "x"}\n    ev["text"] = body.text\n    await start_event(r, "t", "S", ev)',
    "update": 'ev = {"kind": "x"}\n    ev.update(text=body.text)\n    await start_event(r, "t", "S", ev)',
    "ior": 'ev = {"kind": "x"}\n    ev |= {"text": body.text}\n    await start_event(r, "t", "S", ev)',
    "kwargs": 'await start_event(r, "t", "S", **kw)',
    "dict-call": 'await start_event(r, "t", "S", dict(text=body.text))',
    "tham-so-helper": None,  # dựng riêng bên dưới
}


_ROLE_HEAD = "from app.auth.authz import approval_role\nfrom app.graph.late_event import start_event\n"
_ROLE = {  # tên → (thân hàm, khoá chữ tự do KHÔNG sạch mong đợi)
    "vai-tro-tu-approval-role": (('role = approval_role(p, a, x)\n    await start_event(r, "t", "S", {"kind": "approved", '
                                  '"decided_as": role})'), []),
    "decided-as-tu-body": ('await start_event(r, "t", "S", {"kind": "approved", "decided_as": body.role})', ["decided_as"]),
    "gan-lai-tu-body": (('role = approval_role(p, a, x)\n    role = body.role\n'
                         '    await start_event(r, "t", "S", {"decided_as": role})'), ["decided_as"]),
    "gan-sau-cong": (('await start_event(r, "t", "S", {"decided_as": role})\n    role = approval_role(p, a, x)'), ["decided_as"]),
}


@pytest.mark.parametrize("name", sorted(_ROLE))
def test_n1_self_check_decided_as_only_from_approval_role(name: str) -> None:
    """Soát S11 R1: `decided_as` chỉ sạch khi là tên gán từ `approval_role(...)` (import thẳng) — chữ người dùng → đỏ."""
    body, keys = _ROLE[name]
    src = _ROLE_HEAD + f"\nasync def route(d, r, body, p, a, x):\n    {body}\n"
    [(_, bad)] = scan(ast.parse(src)).values()
    assert bad == keys


def test_n1_self_check_decided_as_alias_import_not_trusted() -> None:
    src = ("from app.auth.authz import approval_role as ar\nfrom app.graph.late_event import start_event\n"
           "\nasync def route(r, p, a, x):\n    role = ar(p, a, x)\n    await start_event(r, 't', 'S', {'decided_as': role})\n")
    [(_, bad)] = scan(ast.parse(src)).values()
    assert bad == ["decided_as"]


def _one(src: str) -> tuple[list[str], list[str]]:
    [result] = scan(ast.parse(src)).values()
    return result


def test_n1_self_check_real_route_shape_passes() -> None:
    assert _one(_GOOD) == (["note"], [])


@pytest.mark.parametrize("name", sorted(_BAD))
def test_n1_self_check_leaks_are_flagged(name: str) -> None:
    body, keys = _BAD[name]
    src = _HEAD + f"\nasync def route(d, r, body, runner, x):\n    {body}\n"
    results = scan(ast.parse(src))
    assert any(bad == keys for _, bad in results.values()), results


@pytest.mark.parametrize("name", sorted(k for k in _UNPARSABLE if _UNPARSABLE[k]))
def test_n1_self_check_unparsable_is_red(name: str) -> None:
    src = _HEAD + f"\nasync def route(d, r, body, kw, TEXT):\n    {_UNPARSABLE[name]}\n"
    with pytest.raises(Unparsable):
        scan(ast.parse(src))


def test_n1_self_check_helper_forwarding_is_red() -> None:
    src = _HEAD + "\nasync def send(r, ev):\n    await start_event(r, 't', 'S', ev)\n"
    with pytest.raises(Unparsable):
        scan(ast.parse(src))


def test_n1_self_check_untrusted_redact_is_not_clean() -> None:
    src = ("from app.graph.late_event import start_event\n\ndef redact(d, t):\n    return t\n\n"
           "async def route(d, r, body):\n    red = redact(d, body.text)\n"
           "    await start_event(r, 't', 'S', {'text': red})\n")  # fmt: skip
    assert _one(src) == ([], ["text"])


@pytest.mark.parametrize(
    "src",
    [
        "from app.graph.late_event import start_event as se\n",
        "import functools\nfrom app.graph.late_event import start_event\nf = functools.partial(start_event, None)\n",
        "x = getattr(mod, 'deliver_event')\n",
    ],
    ids=["bi-danh", "partial", "getattr"],
)
def test_n1_self_check_alias_is_red(src: str) -> None:
    assert _sink_references(ast.parse(src))
