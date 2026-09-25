"""Bất biến M5 [Chốt]: policy_engine.evaluate(action, ctx) chỉ 2 tham số, và risk/ không
đụng tới raw_request (phần import-linter không bắt được — 01 mục 4.3)."""

import ast
import inspect
from pathlib import Path

import app.risk
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
