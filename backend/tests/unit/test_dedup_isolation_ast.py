"""M1 — báo trùng yêu cầu KHÔNG vào ngữ cảnh M5 (bất biến 1: M5 không đọc gì ngoài `evaluate(action, ctx)`).

Quét AST: không file nào dưới `app/risk/` import module dedup (`app.domain.dedup`, `DedupConfig`, `get_dedup`, `load_dedup`,
`pick_duplicate`…), và các file dựng `ctx` / quyết định rủi ro (`graph/nodes/b12_assess.py`, `graph/context.py`) không nhắc
`duplicate_of`. `duplicate_of` chỉ là khoá audit điểm log 1 của B3 — không vào state, không vào `ctx`.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
DEDUP_NAMES = {"dedup", "DedupConfig", "get_dedup", "load_dedup", "pick_duplicate", "duplicate_text", "OpenCandidate"}
CTX_FILES = ("graph/nodes/b12_assess.py", "graph/context.py", "risk/context.py")


def dedup_imports(source: str) -> list[str]:
    """Mọi import trỏ tới module/tên dedup: `import app.domain.dedup`, `from app.domain import dedup`, `from x import get_dedup`."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[-1] in DEDUP_NAMES]
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[-1] in DEDUP_NAMES:
                found.append(node.module)
            found += [f"{node.module}.{a.name}" for a in node.names if a.name in DEDUP_NAMES]
    return found


def test_detector_catches_each_import_form() -> None:
    assert dedup_imports("import app.domain.dedup") == ["app.domain.dedup"]
    assert dedup_imports("from app.domain import dedup") == ["app.domain.dedup"]
    assert dedup_imports("from app.domain.dedup import pick_duplicate") == ["app.domain.dedup", "app.domain.dedup.pick_duplicate"]
    assert dedup_imports("from app.settings import get_dedup as g") == ["app.settings.get_dedup"]
    assert dedup_imports("from app.settings import get_policy\nimport os") == []


def test_risk_package_does_not_import_dedup() -> None:
    files = sorted((APP / "risk").rglob("*.py"))
    assert files, "không thấy app/risk — đường dẫn quét sai"
    bad = {str(f.relative_to(APP)): hits for f in files if (hits := dedup_imports(f.read_text(encoding="utf-8")))}
    assert bad == {}


@pytest.mark.parametrize("rel", CTX_FILES)
def test_ctx_builders_never_mention_duplicate_of(rel: str) -> None:
    source = (APP / rel).read_text(encoding="utf-8")
    assert "duplicate_of" not in source and dedup_imports(source) == []


def test_duplicate_of_is_only_written_by_b3() -> None:
    """Khoá `duplicate_of` chỉ xuất hiện ở node B3 (ghi), module dedup, và nơi đọc audit — không ở node nào khác."""
    writers = sorted(
        str(f.relative_to(APP)) for f in (APP / "graph").rglob("*.py") if "duplicate_of" in f.read_text(encoding="utf-8")
    )
    assert writers == ["graph/nodes/b03_classify.py"]
