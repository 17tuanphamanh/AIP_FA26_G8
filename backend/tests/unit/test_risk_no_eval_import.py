"""P10 (phase6 4.1, D-37) — không module nào trong `backend/app/risk/` import `app.eval`. Thay cho một hợp đồng import-linter
(`.importlinter` là file của M9): `app.eval` (T27, T29) import lại `app.risk.decision_math`/`calibrator`, chiều ngược lại cấm
— một nguồn toán, không vòng.

Bộ dò AST bắt: `import app.eval…`, `from app.eval… import …`, `from app import eval`, import tương đối (`from ..eval import …`
giải về tên tuyệt đối theo vị trí file), `importlib.import_module("app.eval…")` / `__import__("app.eval…")` với hằng chuỗi.
Bộ dò theo hằng chuỗi không bắt được import động có alias (`from importlib import import_module as im`), `package=`, hay
tên module tính lúc chạy → cấm hẳn import động trong `app/risk` (`uses_dynamic_import`) — soát bảo mật 6A, Khác 5.
`imported_modules` dùng lại ở cb8 (`test_calibrator.py`).
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
APP_DIR = REPO / "backend" / "app"
RISK_DIR = APP_DIR / "risk"


def _module_name(path: Path, app_dir: Path) -> str:
    rel = path.relative_to(app_dir.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(path: Path, app_dir: Path, level: int, module: str | None) -> str:
    package = _module_name(path, app_dir).split(".")
    if path.name != "__init__.py":
        package.pop()  # module thường: gói chứa nó
    base = package[: len(package) - (level - 1)] if level > 1 else package
    return ".".join([*base, module] if module else base)


def imported_modules(path: Path, app_dir: Path = APP_DIR) -> set[str]:
    """Mọi tên module tuyệt đối mà file `path` import (gồm cả `pkg.name` của `from pkg import name`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(path, app_dir, node.level, node.module) if node.level else (node.module or "")
            found.add(base)
            found |= {f"{base}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if name in {"import_module", "__import__"} and isinstance(node.args[0].value, str):
                found.add(node.args[0].value)
    return found


def uses_dynamic_import(path: Path, app_dir: Path = APP_DIR) -> bool:
    """File import `importlib` (mọi dạng) hoặc gọi/nhắc tới `__import__` / `import_module`."""
    if hits(imported_modules(path, app_dir), "importlib"):
        return True
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {"__import__", "import_module"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in names:
            return True
        if isinstance(node, ast.Attribute) and node.attr in names:
            return True
        if isinstance(node, ast.Constant) and node.value in names:  # getattr(mod, "import_module")
            return True
    return False


def hits(modules: set[str], forbidden: str) -> set[str]:
    return {m for m in modules if m == forbidden or m.startswith(forbidden + ".")}


def risk_files() -> list[Path]:
    return sorted(RISK_DIR.rglob("*.py"))


def test_detector_catches_every_import_form(tmp_path: Path) -> None:
    """Chống xanh giả: bộ dò phải thấy từng dạng import vi phạm (file mẫu đặt giả ở app/risk/x.py)."""
    fake_app = tmp_path / "app"
    (fake_app / "risk").mkdir(parents=True)
    forms = {
        "abs": "import app.eval.metrics\n",
        "from": "from app.eval.metrics import x\n",
        "from_pkg": "from app import eval\n",
        "rel": "from ..eval import metrics\n",
        "rel_pkg": "from .. import eval\n",
        "dyn": "import importlib\nimportlib.import_module('app.eval.stats')\n",
        "dunder": "__import__('app.eval')\n",
    }
    for key, src in forms.items():
        f = fake_app / "risk" / f"{key}.py"
        f.write_text(src, encoding="utf-8")
        assert hits(imported_modules(f, fake_app), "app.eval"), key
    dynamic = {
        "alias": "from importlib import import_module as im\nim('app.eval')\n",
        "package": "import importlib\nimportlib.import_module('.eval', package='app')\n",
        "computed": "import importlib\nname = 'app.' + 'eval'\nimportlib.import_module(name)\n",
        "builtins": "import builtins\nbuiltins.__import__('app.eval')\n",
        "getattr": "import sys\ngetattr(sys.modules['importlib'], 'import_module')('app.eval')\n",
    }
    for key, src in dynamic.items():
        f = fake_app / "risk" / f"dyn_{key}.py"
        f.write_text(src, encoding="utf-8")
        assert uses_dynamic_import(f, fake_app), key
    ok = fake_app / "risk" / "ok.py"
    ok.write_text("import numpy\nfrom app.core.errors import DomainError\nfrom .models import RiskContext\n", encoding="utf-8")
    assert hits(imported_modules(ok, fake_app), "app.eval") == set()
    assert not uses_dynamic_import(ok, fake_app)


def test_risk_scan_is_not_empty() -> None:
    names = {p.name for p in risk_files()}
    assert len(names) >= 6  # quét rỗng/sai thư mục thì phải đỏ, không xanh giả
    assert {"decision_math.py", "calibrator.py", "policy_engine.py", "estimator.py"} <= names


def test_no_risk_module_imports_app_eval() -> None:
    bad = {str(p.relative_to(REPO)): sorted(hits(imported_modules(p), "app.eval")) for p in risk_files()}
    assert {k: v for k, v in bad.items() if v} == {}


def test_no_risk_module_uses_dynamic_import() -> None:
    assert [str(p.relative_to(REPO)) for p in risk_files() if uses_dynamic_import(p)] == []
