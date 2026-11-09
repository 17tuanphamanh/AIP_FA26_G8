"""Nạp script `scripts/eval/<tên>.py` (G9) như module để test gọi `main(argv)` trong cùng tiến trình — `scripts/` không phải gói."""

import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[4]


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"eval_script_{name}", REPO / "scripts" / "eval" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
